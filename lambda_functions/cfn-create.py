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

def create_stack(stack, template):
  cf.create_stack(StackName=stack, TemplateBody=template)

def get_stack_status(stack):
  stack_description = cf.describe_stacks(StackName=stack)
  return stack_description['Stacks'][0]['StackStatus']

def put_job_failure(job, message):
  print('Putting job failure')
  print(message)
  code_pipeline.put_job_failure_result(jobId=job, failureDetails={'message': message, 'type': 'JobFailed'})

def put_job_success(job, message):
  print('Putting job success')
  print(message)
  code_pipeline.put_job_success_result(jobId=job)

def check_stack_update_status(job_id, stack):
  status = get_stack_status(stack)
  if status in ['UPDATE_COMPLETE', 'CREATE_COMPLETE']:
    # If the update/create finished successfully then
    # succeed the job and don't continue.
    put_job_success(job_id, 'Stack update complete')
        
  elif status in ['UPDATE_IN_PROGRESS', 'UPDATE_ROLLBACK_IN_PROGRESS', 
      'UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS', 'CREATE_IN_PROGRESS', 
      'ROLLBACK_IN_PROGRESS']:
    # If the job isn't finished yet then continue it
    continue_job_later(job_id, 'Stack update still in progress') 
       
  else:
    # If the Stack is a state which isn't "in progress" or "complete"
    # then the stack update/create has failed so end the job with
    # a failed result.
    put_job_failure(job_id, 'Update failed: ' + status)

def continue_job_later(job, message):
  # Use the continuation token to keep track of any job execution state
  # This data will be available when a new job is scheduled to continue the current execution
  continuation_token = json.dumps({'previous_job_id': job})
    
  print('Putting job continuation')
  print(message)
  code_pipeline.put_job_success_result(jobId=job, continuationToken=continuation_token)

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
    
    stack_name_prefix = job_params['stack_prefix']
    stack_name = stack_name_prefix + '-' + build_id
    
    if 'continuationToken' in job_data:
      check_stack_update_status(job_id, stack_name)
    else:
      
      template_file = job_params['template']
      template = get_file_in_zip(s3, artifact_data, template_file)
    
      create_stack(stack_name, template)
      continue_job_later(job_id, 'Stack create started')
        
  except Exception as e:
    print('Function failed due to exception.')
    print(e)
    traceback.print_exc()
    put_job_failure(job_id, 'Function exception: ' + str(e))
  
  print('Function complete.')
  return "Complete."
