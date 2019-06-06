var https = require('https');
var zlib = require('zlib');
var crypto = require('crypto');

var AWS = require('aws-sdk');

var endpoint = process.env.ES_ENDPOINT;
var s3bucket = process.env.S3_BUCKET;
var s3prefix = process.env.S3_PREFIX;
var lastError;
var esStatus = 0;
var s3Status = 0;

exports.handler = function(input, context) {
    // decode input from base64
    var zippedInput = new Buffer(input.awslogs.data, 'base64');

    // decompress the input
    zlib.gunzip(zippedInput, function(error, buffer) {
        if (error) { context.fail(error); return; }

        // parse the input from JSON
        var awslogsData = JSON.parse(buffer.toString('utf8'));

        // transform the input to Elasticsearch documents
        var elasticsearchBulkData = transform(awslogsData);
        // transform the input to S3 logs
        var s3BulkData = s3transform(awslogsData);

        // skip control messages
        if (!elasticsearchBulkData) {
            console.log('Received a control message');
            context.succeed('Control message handled successfully');
            return;
        }

        // post documents to the Amazon Elasticsearch Service
        post(elasticsearchBulkData, function(error, success, statusCode, failedItems) {
            console.log('Response: ' + JSON.stringify({
                "statusCode": statusCode
            }));

            if (error) {
                console.log('Error: ' + JSON.stringify(error, null, 2));

                if (failedItems && failedItems.length > 0) {
                    console.log("Failed Items: " +
                        JSON.stringify(failedItems, null, 2));
                }

                endHandler(context, 'es', error);
            } else {
                console.log('Success: ' + JSON.stringify(success));
                endHandler(context, 'es');
            }
        });

        // put log events to S3
        s3putObject(s3BulkData, function(error, data) {
            if (error) {
                console.log('Error: ' + JSON.stringify(error, null, 2));
                endHandler(context, 's3', error);
            }
            else {
                console.log('Success: ' + JSON.stringify(data));
                endHandler(context, 's3');
            }
        });
    });
};

function endHandler(context, caller, error) {
    if (error) {
        lastError = error;
    }

    switch(caller) {
        case "es":
            esStatus = 1;
            break;
        case "s3":
            s3Status = 1;
            break;
        default:
            break;
    }

    if (esStatus === 1 && s3Status === 1) {
        if (lastError) {
            context.fail(JSON.stringify(error));
        }
        else {
            context.succeed('Success');
        }
    }
}

function s3transform(payload) {
    if (payload.messageType === 'CONTROL_MESSAGE') {
        return null;
    }

    var logs = "";

    payload.logEvents.forEach(function(logEvent) {
        var newEntry = {
            id: logEvent.id,
            timestamp: new Date(1 * logEvent.timestamp).toISOString(),
            message: JSON.parse(logEvent.message),
            owner: payload.owner,
            logGroup: payload.logGroup,
            logStream: payload.logStream
        }

        logs = logs + JSON.stringify(newEntry) + "\n";
    });

    return logs;
}

function s3putObject(logEvents, callback) {
    var now = new Date();
    var time_string =
        now.getUTCFullYear() + '-'
        + ('0' + (now.getUTCMonth() + 1)).slice(-2) + '-'
        + ('0' + now.getUTCDate()).slice(-2) + '-'
        + now.getUTCHours() + '-'
        + now.getUTCMinutes() + '-'
        + now.getUTCSeconds();

    var s3params = {
        Bucket: s3bucket,
        Key: s3prefix
            + now.getUTCFullYear() + '/'
            + ('0' + (now.getUTCMonth() + 1)).slice(-2) + '/'
            + ('0' + now.getUTCDate()).slice(-2) + '/'
            + now.getUTCHours() + '/'
            + Math.random().toString(36).substr(2,4) + 'contactflow_' + time_string,
        Body: logEvents
    };

    var s3client = new AWS.S3();
    s3client.putObject(s3params, function(err, data) {
        callback(err, data);
    });
}

function transform(payload) {
    if (payload.messageType === 'CONTROL_MESSAGE') {
        return null;
    }

    var bulkRequestBody = '';

    payload.logEvents.forEach(function(logEvent) {
        var timestamp = new Date(1 * logEvent.timestamp);

        // index name format: cwl-YYYY.MM.DD
        var indexName = [
            'cwl-' + timestamp.getUTCFullYear(),              // year
            ('0' + (timestamp.getUTCMonth() + 1)).slice(-2),  // month
            ('0' + timestamp.getUTCDate()).slice(-2)          // day
        ].join('.');

        var source = buildSource(logEvent.message, logEvent.extractedFields);
        source['@id'] = logEvent.id;
        source['@timestamp'] = new Date(1 * logEvent.timestamp).toISOString();
        source['@message'] = logEvent.message;
        source['@owner'] = payload.owner;
        source['@log_group'] = payload.logGroup;
        source['@log_stream'] = payload.logStream;

        var action = { "index": {} };
        action.index._index = indexName;
        action.index._type = payload.logGroup;
        action.index._id = logEvent.id;

        bulkRequestBody += [
            JSON.stringify(action),
            JSON.stringify(source),
        ].join('\n') + '\n';
    });
    return bulkRequestBody;
}

function buildSource(message, extractedFields) {
    if (extractedFields) {
        var source = {};

        for (var key in extractedFields) {
            if (extractedFields.hasOwnProperty(key) && extractedFields[key]) {
                var value = extractedFields[key];

                if (isNumeric(value)) {
                    source[key] = 1 * value;
                    continue;
                }

                jsonSubString = extractJson(value);
                if (jsonSubString !== null) {
                    source['$' + key] = JSON.parse(jsonSubString);
                }

                source[key] = value;
            }
        }
        return source;
    }

    jsonSubString = extractJson(message);
    if (jsonSubString !== null) {
        return JSON.parse(jsonSubString);
    }

    return {};
}

function extractJson(message) {
    var jsonStart = message.indexOf('{');
    if (jsonStart < 0) return null;
    var jsonSubString = message.substring(jsonStart);
    return isValidJson(jsonSubString) ? jsonSubString : null;
}

function isValidJson(message) {
    try {
        JSON.parse(message);
    } catch (e) { return false; }
    return true;
}

function isNumeric(n) {
    return !isNaN(parseFloat(n)) && isFinite(n);
}

function post(body, callback) {
    var requestParams = buildRequest(endpoint, body);

    var request = https.request(requestParams, function(response) {
        var responseBody = '';
        response.on('data', function(chunk) {
            responseBody += chunk;
        });
        response.on('end', function() {
            var info = JSON.parse(responseBody);
            var failedItems;
            var success;

            if (response.statusCode >= 200 && response.statusCode < 299) {
                failedItems = info.items.filter(function(x) {
                    return x.index.status >= 300;
                });

                success = {
                    "attemptedItems": info.items.length,
                    "successfulItems": info.items.length - failedItems.length,
                    "failedItems": failedItems.length
                };
            }

            var error = response.statusCode !== 200 || info.errors === true ? {
                "statusCode": response.statusCode,
                "responseBody": responseBody
            } : null;

            callback(error, success, response.statusCode, failedItems);
        });
    }).on('error', function(e) {
        callback(e);
    });
    request.end(requestParams.body);
}

function buildRequest(endpoint, body) {
    var endpointParts = endpoint.match(/^([^\.]+)\.?([^\.]*)\.?([^\.]*)\.amazonaws\.com$/);
    var region = endpointParts[2];
    var service = endpointParts[3];
    var datetime = (new Date()).toISOString().replace(/[:\-]|\.\d{3}/g, '');
    var date = datetime.substr(0, 8);
    var kDate = hmac('AWS4' + process.env.AWS_SECRET_ACCESS_KEY, date);
    var kRegion = hmac(kDate, region);
    var kService = hmac(kRegion, service);
    var kSigning = hmac(kService, 'aws4_request');

    var request = {
        host: endpoint,
        method: 'POST',
        path: '/_bulk',
        body: body,
        headers: {
            'Content-Type': 'application/json',
            'Host': endpoint,
            'Content-Length': Buffer.byteLength(body),
            'X-Amz-Security-Token': process.env.AWS_SESSION_TOKEN,
            'X-Amz-Date': datetime
        }
    };

    var canonicalHeaders = Object.keys(request.headers)
        .sort(function(a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; })
        .map(function(k) { return k.toLowerCase() + ':' + request.headers[k]; })
        .join('\n');

    var signedHeaders = Object.keys(request.headers)
        .map(function(k) { return k.toLowerCase(); })
        .sort()
        .join(';');

    var canonicalString = [
        request.method,
        request.path, '',
        canonicalHeaders, '',
        signedHeaders,
        hash(request.body, 'hex'),
    ].join('\n');

    var credentialString = [ date, region, service, 'aws4_request' ].join('/');

    var stringToSign = [
        'AWS4-HMAC-SHA256',
        datetime,
        credentialString,
        hash(canonicalString, 'hex')
    ] .join('\n');

    request.headers.Authorization = [
        'AWS4-HMAC-SHA256 Credential=' + process.env.AWS_ACCESS_KEY_ID + '/' + credentialString,
        'SignedHeaders=' + signedHeaders,
        'Signature=' + hmac(kSigning, stringToSign, 'hex')
    ].join(', ');

    return request;
}

function hmac(key, str, encoding) {
    return crypto.createHmac('sha256', key).update(str, 'utf8').digest(encoding);
}

function hash(str, encoding) {
    return crypto.createHash('sha256').update(str, 'utf8').digest(encoding);
}