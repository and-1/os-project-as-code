#!/usr/bin/env python
# This is simple script, which get changed files from gitlab api
import os
import re
import sys
import requests

files = []
mask = '.*\.env$'
# Create body and header request
try:
  headers = {'Private-Token': os.environ['API_TOKEN']}
  url = os.environ['CI_API_V4_URL']+"/projects/"+os.environ['CI_PROJECT_ID']+"/repository/commits/"+os.environ['CI_COMMIT_SHA']+"/diff"
except KeyError as key:
  print("Coundn't get {} environment variable".format(key))
  sys.exit(1)
# Try get response from API
try:
  result = requests.get(url, headers=headers)
except ConnectionError:
  print("Couldn't connect to server")
  sys.exit(1)
try:
  result.raise_for_status()
except requests.exceptions.HTTPError:
  print("Server return don't success status - {}".format(result.status_code))
  sys.exit(1)
# Parse result
for file in result.json():
  if re.match(mask, file['new_path']):
    if file['renamed_file']:
      files.append(file['old_path']+'@'+file['new_path'])
    elif file['deleted_file']:
      files.append('d@'+file['new_path'])
    else:
      files.append(file['new_path'])

print(' '.join(files))
