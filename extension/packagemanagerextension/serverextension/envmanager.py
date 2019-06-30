# pylint: disable=C0321

import json
import os
import re
import uuid
import yaml

from subprocess import check_output, CalledProcessError
from packaging.version import parse

from traitlets.config.configurable import LoggingConfigurable
from traitlets import Dict


def pkg_info(s):
    return {
        "build_string": s.get("build_string", s.get("build")),
        "name": s.get("name"),
        "version": s.get("version")
    }


def pkg_info_status(s, names):
    pkg_info_res = pkg_info(s)
    name = pkg_info_res.get("name")
    status = "not available"
    if name in names:
        status = "installed"
    pkg_info_res['status'] = status
    return pkg_info_res


MAX_LOG_OUTPUT = 6000

CONDA_EXE = os.environ.get("CONDA_EXE", "conda")  # type: str

# try to match lines of json
JSONISH_RE = r'(^\s*["\{\}\[\],\d])|(["\}\}\[\],\d]\s*$)'

# these are the types of environments that can be created
package_map = {
    'python2': 'python=2 ipykernel',
    'python3': 'python=3 ipykernel'
}


class EnvManager(LoggingConfigurable):
    envs = Dict()

    def conda_execute(self, cmd, *args):
        cmd = CONDA_EXE + ' ' + cmd
        cmdline = cmd.split() + list(args)
        self.log.debug('[packagemanagerextension] command: %s', cmdline)

        try:
            output = check_output(cmdline)
        except CalledProcessError as exc:
            self.log.debug(
                '[packagemanagerextension] exit code: %s', exc.returncode)
            output = exc.output

        self.log.debug('[packagemanagerextension] output: %s',
                       output[:MAX_LOG_OUTPUT])

        if len(output) > MAX_LOG_OUTPUT:
            self.log.debug('[packagemanagerextension] ...')

        return output.decode("utf-8")

    def list_projects(self):
        """List all projects that conda knows about"""
        info = self.clean_conda_json(self.conda_execute('info --json'))

        def get_info(env):
            return {
                'name': os.path.basename(env),
                'dir': env
            }

        return {
            "projects": [get_info(env) for env in info['envs'] if "swanproject" in env]
        }

    def clean_conda_json(self, output):
        lines = output.splitlines()

        try:
            return json.loads('\n'.join(lines))
        except Exception as err:
            self.log.warn(
                '[packagemanagerextension] JSON parse fail:\n%s', err)

        # try to remove bad lines
        lines = [line for line in lines if re.match(JSONISH_RE, line)]

        try:
            return json.loads('\n'.join(lines))
        except Exception as err:
            self.log.error(
                '[packagemanagerextension] JSON clean/parse fail:\n%s', err)

        return {"error": True}

    def delete_project(self, directory):
        env = ""
        directory = str(directory) + ".swanproject"
        try:
            env = yaml.load(open(directory))['ENV']
        except:
            return {'error': "Can't find project"}
        output = self.conda_execute('remove -y -q --all --json -n', env)
        kdir = '.local/share/jupyter/kernels/' + env
        os.remove(kdir + '/kernel.json')
        os.rmdir(kdir)
        return self.clean_conda_json(output)

    def project_info(self, directory):
        env = ""
        names = []
        packagesMD = {}
        directory = str(directory) + ".swanproject"
        try:
            val = yaml.load(open(directory))
            env = val['ENV']
            packagesMD = val['PACKAGE_INFO']
        except:
            return {'error': "Can't find project"}

        for item in packagesMD:
            names.append(item.get('name'))

        output = self.conda_execute('list --no-pip --json -n', env)
        data = self.clean_conda_json(output)
        if 'error' in data:
            # we didn't get back a list of packages, we got a dictionary with
            # error info
            return data

        return {
            "env": env,
            "packages": [pkg_info_status(package, names) for package in data]
        }

    def export_env(self, directory):
        env = ""
        directory = str(directory) + ".swanproject"
        try:
            env = yaml.load(open(directory))['ENV']
        except:
            return {'error': "Can't find project"}
        return str(self.conda_execute('list -e -n', env))

    def clone_env(self, env, name):
        output = self.conda_execute('create -y -q --json -n', name,
                               '--clone', env)
        return self.clean_conda_json(output)

    def create_project(self, directory, type):
        name = uuid.uuid1()
        name = 'swanproject-' + str(name)
        data = {'ENV': name}

        folder = directory[:-1].split('/')[-1]

        if not os.path.exists(directory):
            # os.makedirs(directory)
            res = {'error': 'Project directory not available'}
            return res

        # if os.path.isfile(directory + '.swanproject'):
        #     res = {'error': 'This directory alreday contains a project'}
        #     return res

        packages = package_map[type]
        output = self.conda_execute('create -y -q --json -n', name,
                               *packages.split(" "))
        packages = self.conda_execute('list --no-pip --json -n', name)
        packages = self.clean_conda_json(packages)
        op = self.clean_conda_json(output)
        tp = json.dumps(op)
        js = json.loads(tp)
        kerneljson = {
            "argv": [js['prefix'] + "/bin/python",   "-m",
                     "ipykernel_launcher",
                     "-f",
                     "{connection_file}"],
            "display_name": "Python (" + folder + ")",
            "language": "python"
        }
        kdir = '.local/share/jupyter/kernels/' + name
        if not os.path.exists(kdir):
            os.makedirs(kdir)
        with open(kdir + '/kernel.json', 'w') as fp:
            json.dump(kerneljson, fp)

        data['PACKAGE_INFO'] = packages
        with open(directory + '.swanproject', 'w') as outfile:
            yaml.dump(data, outfile, default_flow_style=False)
        return op

    def check_update(self, directory):
        env = ""
        directory = str(directory) + ".swanproject"
        try:
            env = yaml.load(open(directory))['ENV']
        except:
            return {'error': "Can't find project"}
        packagesJson = self.conda_execute('list --no-pip --json -n', env)
        packagesJson = self.clean_conda_json(packagesJson)
        packages = []
        for it in packagesJson:
            packages.append(it.get('name'))
        output = self.conda_execute('update --dry-run -q --json -n', env,
                               *packages)
        data = self.clean_conda_json(output)

        if 'error' in data:
            # we didn't get back a list of packages, we got a dictionary with
            # error info
            return data
        elif 'actions' in data:
            links = data['actions'].get('LINK', [])
            package_versions = [link for link in links]
            return {
                "updates": [pkg_info(pkg_version)
                            for pkg_version in package_versions]
            }
        else:
            # no action plan returned means everything is already up to date
            return {
                "updates": []
            }

    def install_packages(self, directory, packages):
        env = ""
        directory = str(directory) + ".swanproject"
        try:
            env = yaml.load(open(directory))['ENV']
        except:
            return {'error': "Can't find project"}
        output = self.conda_execute('install -y -q --json -n', env, *packages)
        data = {'ENV': env}
        packages = self.conda_execute('list --no-pip --json -n', env)
        packages = self.clean_conda_json(packages)
        data['PACKAGE_INFO'] = packages
        with open(directory, 'w') as outfile:
            yaml.dump(data, outfile, default_flow_style=False)
        return self.clean_conda_json(output)

    def update_packages(self, directory, packages):
        env = ""
        directory = str(directory) + ".swanproject"
        try:
            env = yaml.load(open(directory))['ENV']
        except:
            return {'error': "Can't find project"}
        output = self.conda_execute('update -y -q --json -n', env, *packages)
        data = {'ENV': env}
        packages = self.conda_execute('list --no-pip --json -n', env)
        packages = self.clean_conda_json(packages)
        data['PACKAGE_INFO'] = packages
        with open(directory, 'w') as outfile:
            yaml.dump(data, outfile, default_flow_style=False)
        return self.clean_conda_json(output)

    def remove_packages(self, directory, packages):
        env = ""
        directory = str(directory) + ".swanproject"
        try:
            env = yaml.load(open(directory))['ENV']
        except:
            return {'error': "Can't find project"}
        output = self.conda_execute('remove -y -q --json -n', env, *packages)
        data = {'ENV': env}
        packages = self.conda_execute('list --no-pip --json -n', env)
        packages = self.clean_conda_json(packages)
        data['PACKAGE_INFO'] = packages
        with open(directory, 'w') as outfile:
            yaml.dump(data, outfile, default_flow_style=False)
        return self.clean_conda_json(output)

    def package_search(self, q):
        # this method is slow and operates synchronously
        output = self.conda_execute('search --json', q)
        data = self.clean_conda_json(output)

        if 'error' in data:
            # we didn't get back a list of packages, we got a dictionary with
            # error info
            return data

        packages = []

        for entries in data.values():
            max_version = None
            max_version_entry = None

            for entry in entries:
                version = parse(entry.get("version", ""))

                if max_version is None or version > max_version:
                    max_version = version
                    max_version_entry = entry

            packages.append(max_version_entry)

        return {"packages": sorted(packages, key=lambda entry: entry.get("name"))}
