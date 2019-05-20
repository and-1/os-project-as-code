# Script for make declarative and easily creating/updating project in OpenStack using HEAT

Descriptions of paramters in config files avaliable in global.yaml, projects/project.env.example

For see avaliable keys of deploy.py use:
```bash
./deploy.py -h
```

This repository ready for using with gitlab-ci. See .gitlab-ci.yml.

# deploy.py
Deploy.py script expect two environment variables:
 - $KS_PASS - keystone user password, for connection to it
 - $FILE_LIST - space separated list of project config files, which will be deployed

Name of project config file will be name of OS stack name

Deploy.py runs with --all flag:
 - if $FILE_LIST exist, will be updated only given projects
 - if $FILE_LIST not exist, will be updated all projects in projects dir

Using gitlab-ci, $FILE_LIST contain new or changed files. Run tools/get_changes.py for get that list
That script expects env variable $API_TOKEN, which contains gitlab-ci access token

# TODO
- [ ] Resolve problem with user password. How does it set?
- [ ] Add RBAC permission to TungstenFubric project
