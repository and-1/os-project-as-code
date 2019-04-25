#!/usr/bin/env python
import os
import re
import yaml
import argparse
import sys
from keystoneauth1 import loading, session, exceptions
from keystoneclient.v3 import client as ks_client

sys.path.append(os.environ['PWD'])
from deploy import proj_stack

def load_yaml(fname):
  try:
    with open(fname) as f:
      content = yaml.safe_load(f)
  except IOError:
    print("ERROR: Couldn't open file {}".format(fname))
    sys.exit(1)
  except yaml.YAMLError as err:
    print("ERROR: Couldn't parse project yaml file {}: {}".format(fname, err))
    sys.exit(1)
  return content

def ks_sess(globs):
    loader= loading.get_plugin_loader('password')
    auth= loader.load_from_options(auth_url=globs['auth_url'],
                                                      username=globs['ks_username'],
                                                      password=os.environ['KS_PASS'],
                                                      project_name=globs['ks_project'],
                                                      user_domain_name=globs['ks_domain'],
                                                      project_domain_name=globs['ks_domain'])
    sess = session.Session(auth=auth)
    return sess

  
glob_file = './global.yaml'
parser = argparse.ArgumentParser(description='Check values of config files')
parser.add_argument('--type', required=True, help='what config type will be check', choices=['global', 'project'])
args = parser.parse_args()

if args.type == 'project':
  try:
    project_files = os.environ['FILE_LIST'].split(' ')
  except KeyError:
    print("ERROR: Couldn't get changed list of files")
    sys.exit(1)
  for conf in project_files:
    if re.match('^[^@]*$', conf):
      proj_conf = load_yaml(conf)
      glob_conf = load_yaml(glob_file)
    # check regions
    if not set(proj_conf['regions'].keys()).issubset(set(glob_conf['regions'].keys())):
      bad_regions = set(proj_conf['regions'].keys()).difference(set(glob_conf['regions'].keys()))
      for region in bad_regions:
        print('ERROR: {} is not exist, check avaliable regions in file {}'.format(region, glob_file))
      sys.exit(1)
    check_flag = False
    for region in proj_conf['regions'].keys():
      # check domain
      if proj_conf['domain'] != glob_conf['regions'][region]['domain']:
        print("ERROR: Region {} isn't avaliable with domain {}, check avaliable domain for region in file {}".format(region, proj_conf['domain'], glob_file))
        check_flag = True
      # check network scopes
      for scope in proj_conf['regions'][region]['net_scopes'].keys():
        if scope not in glob_conf['regions'][region]['net_scopes'].keys():
          print("ERROR: network scope {} isn't exist in region {}, check avaliable scopes in region in file {}".format(scope, region, glob_file))
          check_flag = True 
        if not re.match('(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?){1}\/(?:3[01]|[12][0-9]|[1-9])$', proj_conf['regions'][region]['net_scopes'][scope]['cidr']):
          print("ERROR: {} - wrong cidr value in scope {} ({})".format(proj_conf['regions'][region]['net_scopes'][scope]['cidr'], scope, region))
          check_flag = True 
    if check_flag: sys.exit(1)
    # check users
    if not isinstance(proj_conf['users'], list) or len(proj_conf['users']) < 1:
      print('ERROR: Must be one user in project at least')
      sys.exit(1)
    # check heat template
    stack = proj_stack(glob_conf)
    stack.apply(conf, check=True)
    

if args.type == 'global':
  glob_conf = load_yaml(glob_file)

  # check connection to ks
  try:
    ks_sess(glob_conf).get_token()
  except exceptions.connection.ConnectFailure:  
    print("ERROR: couldn't get ks token, check auth_url parameter")
    sys.exit(1)
  except exceptions.http.Unauthorized:
    print("ERROR: couldn't get ks token, check credential parameters")
    sys.exit(1)
  # check regions in ks
  regions_list = [region.id for region in ks_client.Client(session=ks_sess(glob_conf), interface='public').regions.list()]
  if not set(glob_conf['regions'].keys()).issubset(set(regions_list)):
    for region in set(glob_conf['regions'].keys()).difference(set(regions_list)):
      print("ERROR: {} is not exist in OpenStack".format(region))
    sys.exit(1)
  main_r=0
  for region,data in glob_conf['regions'].items():
    if data.get('main', False):
      main_r +=1
    # check dns forwarder format 
    if not re.match('(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?){1}$', data.get('dns_forwarder', "") ):
      print("ERROR: dns_forwarder in region {} has wrong value or don't exist".format(region))
      sys.exit(1)
    # check route target format
    for scope, rts in data['net_scopes'].items():
      for rt, val in rts.items():
        if not re.match('^\d{1,5}:\d{1,8}$', str(val)):
          print("ERROR: {} has wrong value".format(rt))
          sys.exit(1)
    # check is required keys
    if not data.get('domain', False):
      print("ERROR: domain key must be present in all regions")
      sys.exit(1)
    if not data.get('region_dns_suffix', False):
      print("ERROR: region_dns_suffix key must be present in all regions")
      sys.exit(1)
  # check main domain
  if main_r != 1:
    print("ERROR: main flag doesn't present or present one more time")
    sys.exit(1)
  # check common project template
  stack = proj_stack(glob_conf)
  stack.common_stack(conf, check=True)

