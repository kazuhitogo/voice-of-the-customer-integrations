# quickstart-connect-voci

This solution is based off of two initial solutions:
1) A re:Invent demo that indexed Audio and the CTR into Elastic Search: https://s3.amazonaws.com/serverless-analytics/reinvent-2018-comprehend-transcribe-connect/index.html
2) A blog post that indexed Agent Events and CWL into Elastic Search: https://aws.amazon.com/blogs/contact-center/use-amazon-connect-data-in-real-time-with-elasticsearch-and-kibana/

## Directions

- Create an S3 bucket with a top level folder and copy all files into it from GitHub (https://github.com/aws-quickstart/quickstart-connect-voci)
- Create a stack with the template url set to the s3 bucket you just created under /templates/quickstart-connect-voci-base-pipeline.yaml
    - The QuickSight S3 bucket and folder should be set to the one that you created in step one
    - The S3 audio bucket will be a new bucket, so add a globally unique name
    - The log group is the log group set for the Amazon Connect instance you want to use. You can see the value in the Amazon Connect AWS Console when viewing the instance details under Contact Flow.
- Once the stacks deploy, update your Amazon Connect instance to use the new resources created
    - S3 call recording bucket: the one created by the CF stack
    - Data Streaming CTR: the one created by the CF stack with "AmazonConnectCtrDelivery" in the name (not the Connect-CTR-Stream) **double check this**
    - Agent Event Stream: the one created by the stack with "AgentKinesisStream" in the name
- Follow the directions in the re:Invent link above to log into Kibana with the Cognito user
- Follow the directions in both the links above to configure the Kibana dashboards
    - Note: The index pattern that was named 'reinvent-2018-workshop' is now broken up into two indices: 'call-transcript' & 'ctr'
