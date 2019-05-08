#!/usr/bin/env python
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
import os
import re
import sys
import collections
from keystoneauth1 import loading, session
from keystoneclient.v3 import client as ks_client
from heatclient import client, exc as hexc
from heatclient.common import template_format
import time
import argparse

class proj_stack():
  def __init__(self, glob_conf):
    self.__globs__ = glob_conf
    self.__heat__ = {}
    self.__loader__ = loading.get_plugin_loader('password')
    self.__auth__ = self.__loader__.load_from_options(auth_url=self.__globs__['auth_url'],
                                                      username=self.__globs__['ks_username'],
                                                      password=os.environ['KS_PASS'],
                                                      project_name=self.__globs__['ks_project'],
                                                      user_domain_name=self.__globs__['ks_domain'],
                                                      project_domain_name=self.__globs__['ks_domain'])
    self.__sess__ = session.Session(auth=self.__auth__)
    for region in self.__globs__['regions'].keys():
      self.__heat__[region] = client.Client('1', session=self.__sess__, region_name=region)

  def __dict_merge__(self, dct, merge_dct, add_keys=True):
      dct = dct.copy()
      if not add_keys:
          merge_dct = {
              k: merge_dct[k]
              for k in set(dct).intersection(set(merge_dct))
          }
      for k, v in merge_dct.items():
        if k in ['net_scopes']:
          add_keys=False
        else:
          add_keys=True
        if isinstance(dct.get(k), dict) and isinstance(v, collections.Mapping):
          dct[k] = self.__dict_merge__(dct[k], v, add_keys)
        elif isinstance(v, collections.Mapping):
          dct[k] = self.__dict_merge__({}, merge_dct[k], add_keys)
        else:
          dct[k] = v
      return dct

  def __uniq_list__(self, list_roles):
    list_set = set(list_roles)
    return list(list_set)

  def apply(self, conf_file, check=False):
    # Get content of project config file
    try:
      with open(conf_file) as f:
        project_dict = yaml.safe_load(f)
    except IOError:
      print("Counldn't open file {}".format(conf_file))
      sys.exit(1)
    except yaml.YAMLError as exc:
      print("Error parse project file: {}".format(exc))
      sys.exit(1)
    # Get main region
    for region, data in self.__globs__['regions'].items():
      if data.get('main', False): ks_region = region
    # Merge global and project config
    merged_dict = self.__dict_merge__(project_dict, self.__globs__)
    # set main region to first position
    regions_data = collections.OrderedDict({k:v for k,v in merged_dict['regions'].items() if k == ks_region})
    for k,v in merged_dict['regions'].items():
      if k != ks_region: regions_data.__setitem__(k, v)
    # get domain id to find project
    keystone = ks_client.Client(session=self.__sess__, interface='public')
    dom_names = {dom.name: dom.id for dom in keystone.domains.list()}
    # Prepare vars for template
    common = { k:v for k,v in merged_dict.items() if k != 'regions' }
    common['roles'] = self.__uniq_list__([user.get('role', self.__globs__['default_role']) for user in merged_dict['users'] ])
    env = Environment(
             loader=FileSystemLoader('./templates'),
             autoescape=select_autoescape(['j2'])
          )
    template_hot = env.get_template('project_HOT.j2')
    for region, data in regions_data.items():
      os_stacks = {name.stack_name: name.id for name in self.__heat__[region].stacks.list()}
      # check existing common stack
      if 'project_commons' not in os_stacks.keys() and not check:
        self.common_stack(regions=[region], action={region: 'create'})
      # Prepare HOT env
      hot_env = {}
      hot_env['parameters']= {k: v for k,v in merged_dict.items() if k != 'regions' and k in ['project', 'domain']}
      hot_env['parameters'].update({k:v for k,v in data.items() if k not in ['net_scopes','quotas', 'dns_forwarder']})
      hot_env['parameters'].update({k:v for k,v in data.get('quotas',{}).items()})
      hot_env['parameters'].update({net.lower()+'_'+k:v for net,spec in data.get('net_scopes',{}).items() for k,v in spec.items()})
      if not data.get('main', False):
        time_wait=0
        while self.__globs__['timeout'] - time_wait > 0:
          if check:
            proj_names = {hot_env['parameters']['project']: '12345678-1234-5678-1234-567812345678'}
          else:
            proj_names = {proj.name: proj.id for proj in keystone.projects.list(domain=dom_names[merged_dict['domain']])}
          if merged_dict['project'] in proj_names:
            hot_env['parameters']['project'] = proj_names[merged_dict['project']]
            break
          time.sleep(2)
          time_wait += 2
        else:
          print("Couldn't get project id, timeout exceeded")
          sys.exit(1)
      # Render template
      hot = template_hot.render(common, **data)
      hot_tmpl = template_format.parse(hot)
      stack_name = re.sub('\.[a-z]*$', '',  os.path.basename(conf_file))
      if check: 
        try: 
          self.__heat__[region].stacks.preview(
                                               stack_name=stack_name+'_tmp',
                                               template=hot_tmpl,
                                               environment=hot_env,
                                               disable_rollback='true',
                                               )
        except hexc.HTTPBadRequest as err:
          print(str(err))
      elif stack_name in os_stacks.keys():
        try:
          self.__heat__[region].stacks.update(
                                              stack_id=os_stacks[stack_name],
                                              template=hot_tmpl,
                                              environment=hot_env,
                                              disable_rollback='true',
                                              wait='true',
                                              )
        except hexc.HTTPBadRequest as err:
          print(str(err))
      else:
        try:
          self.__heat__[region].stacks.create(
                                              stack_name=stack_name,
                                              template=hot_tmpl,
                                              environment=hot_env,
                                              disable_rollback='true',
                                              wait='true',
                                              )
        except hexc.HTTPBadRequest as err:
          print(str(err))

  def delete(self, conf_file):
    # delete stack with project
    for region, data in self.__globs__['regions'].items():
      os_stacks = {name.stack_name: name.id for name in self.__heat__[region].stacks.list()}
      stack_name = re.sub('\.[a-z]*$', '',  os.path.basename(conf_file))
      if stack_name in os_stacks.keys():
        self.__heat__[region].stacks.delete(stack_id=os_stacks[stack_name])

  def common_stack(self, regions=[], action={}, check=False):
    if len(regions) == 0:
      regions = self.__globs__['regions'].keys()
    env = Environment(
             loader=FileSystemLoader('./templates'),
             autoescape=select_autoescape(['j2'])
          )
    template_hot = env.get_template('comm_project_HOT.j2')
    for region in regions:
      os_stacks = {name.stack_name: name.id for name in self.__heat__[region].stacks.list()}
      if region not in action:
        act = 'update' if 'project_commons' in os_stacks.keys() else 'create'
      else:
        act = action[region]
      hot_env = {}
      hot_env['parameters'] = {k:v for k,v in self.__globs__['regions'][region].items() if k != 'net_scopes'}
      tmpl_env = hot_env['parameters'].copy()
      tmpl_env['net_scopes'] = [scope for scope, data in self.__globs__['regions'][region].get('net_scopes',{}).items()]
      hot = template_hot.render(**tmpl_env)
      hot_tmpl = template_format.parse(hot)
      stack_name = "project_commons"
      if check:
        try:
          self.__heat__[region].stacks.preview(
                                              stack_name=stack_name+'_tmp',
                                              template=hot_tmpl,
                                              environment=hot_env,
                                              disable_rollback='true',
                                              )
        except hexc.HTTPBadRequest as err:
          print(str(err))
      elif act == 'update':
        try:
          self.__heat__[region].stacks.update(
                                              stack_id=os_stacks[stack_name],
                                              template=hot_tmpl,
                                              environment=hot_env,
                                              disable_rollback='true',
                                              wait='true',
                                              )
        except hexc.HTTPBadRequest as err:
          print(str(err))
      elif act == 'create': 
        try:
          self.__heat__[region].stacks.create(
                                              stack_name=stack_name,
                                              template=hot_tmpl,
                                              environment=hot_env,
                                              disable_rollback='true',
                                              wait='true',
                                              )
        except hexc.HTTPBadRequest as err:
          print(str(err))
      

if __name__ == "__main__":
  global_file = "global.yaml"
  project_path = 'projects'
  timeout = 60

  parser = argparse.ArgumentParser(description='Create os stacks with project configs')
  parser.add_argument('--all', help='deploy/update project_common os stack', action='store_true')
  args = parser.parse_args()

  try: 
    project_files = os.environ['FILE_LIST'].split(' ')
  except KeyError:
    if args.all:
      project_files = [os.path.join(project_path,f) for f in os.listdir(project_path) if os.path.isfile(os.path.join(project_path, f))]
    else:
      print("Couldn't find environment variable $FILE_LIST")
      sys.exit(1)
  try: 
    with open(global_file) as f:
      global_dict = yaml.safe_load(f)
      global_dict['timeout']= timeout
  except IOError:
    print("Couldn't open file {}".format(global_file))
    sys.exit(1)
  except yaml.YAMLError as err:
    print('Error parse region yaml file: {}'.format(err))
    sys.exit(1)

  project = proj_stack(global_dict)
  if args.all:
    project.common_stack()
  for file in project_files:
    if re.match('^d@[^@]*$', file):
      project.delete(file.replace('d@',''))
    if re.match('^[^@]*', file):
      project.apply(file)
    if re.match('^[^@]*\.@[^@]*$', file):
      print("ERROR: remane project file is not supported")
      sys.exit(1)
