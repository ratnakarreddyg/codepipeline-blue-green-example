# Taken from CodePipeline User Guide : http://docs.aws.amazon.com/codepipeline/latest/userguide/codepipeline-user.pdf

from boto3.session import Session

import json
import boto3
import botocore
import zipfile
import tempfile
import traceback

import pprint

cf            = boto3.client('cloudformation')
code_pipeline = boto3.client('codepipeline')
autoscaling   = boto3.client('autoscaling')

def find_artifact(artifacts, name):
  for artifact in artifacts:
    if artifact['name'] == name:
      return artifact
  raise Exception('Input artifact named "{0}" not found in event'.format(name))

def get_file_in_zip(s3, artifact, file_in_zip):
  tmp_file = tempfile.NamedTemporaryFile()
  bucket = artifact['location']['s3Location']['bucketName']
  key = artifact['location']['s3Location']['objectKey']
  
  with tempfile.NamedTemporaryFile() as tmp_file:
    s3.download_file(bucket, key, tmp_file.name)
    with zipfile.ZipFile(tmp_file.name, 'r') as zip:
      return zip.read(file_in_zip)

def setup_s3_client(job_data):
  key_id = job_data['artifactCredentials']['accessKeyId']
  key_secret = job_data['artifactCredentials']['secretAccessKey']
  session_token = job_data['artifactCredentials']['sessionToken']
    
  session = Session(aws_access_key_id=key_id,
    aws_secret_access_key=key_secret,
    aws_session_token=session_token)
  return session.client('s3', config=botocore.client.Config(signature_version='s3v4'))

def get_param_dict(job_params):
  param_dict = dict()
  pairs = job_params.split(',')
  for pair in pairs:
    kv = pair.split('=')
    param_dict[ kv[0].strip() ] = kv[1].strip()

  return param_dict

def put_job_failure(job, message):
  print('Putting job failure')
  print(message)
  code_pipeline.put_job_failure_result(jobId=job, failureDetails={'message': message, 'type': 'JobFailed'})

def put_job_success(job, message):
  print('Putting job success')
  print(message)
  code_pipeline.put_job_success_result(jobId=job)

def associate_asg_with_elb(asgStackName, elbStackName):
  
  asg_resource = cf.describe_stack_resources(StackName=asgStackName, LogicalResourceId="WebAutoScalingGroup")
  asg_name = asg_resource['StackResources'][0]['PhysicalResourceId']
  
  elb_resource = cf.describe_stack_resources(StackName=elbStackName, LogicalResourceId="ELB")
  elb_name = elb_resource['StackResources'][0]['PhysicalResourceId']
  
  resp = autoscaling.attach_load_balancers(AutoScalingGroupName=asg_name, LoadBalancerNames=[elb_name])
  print resp

def handler(event, context):
  
  try:
    
    pp = pprint.PrettyPrinter(indent=4)
    pp.pprint(event)
    
    job_id     = event['CodePipeline.job']['id']
    job_data   = event['CodePipeline.job']['data']
    artifacts = job_data['inputArtifacts']
    job_params = get_param_dict(job_data['actionConfiguration']['configuration']['UserParameters'])
    
    print 'Job ID: ' + job_id
    
    s3 = setup_s3_client(job_data)
    
    artifact = job_params['artifact']
    artifact_data = find_artifact(artifacts, artifact)
    
    build_id = get_file_in_zip(s3, artifact_data, 'BUILD_ID')
    build_id = build_id.strip()
    
    asg_stack_prefix = job_params['asg_stack_prefix']
    asg_stack_name = asg_stack_prefix + '-' + build_id
    
    elb_stack_prefix = job_params['elb_stack_prefix']
    elb_stack_name = elb_stack_prefix + '-' + build_id
    
    associate_asg_with_elb(asg_stack_name, elb_stack_name)
    
  except Exception as e:
    print('Function failed due to exception.')
    print(e)
    traceback.print_exc()
    put_job_failure(job_id, 'Function exception: ' + str(e))
  
  print('Function complete.')
  return "Complete."
