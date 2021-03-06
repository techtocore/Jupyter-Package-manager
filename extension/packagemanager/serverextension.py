'''
This is the entrypoint module for Jupyter Server Extension
'''

# Tornado get and post handlers often have different args from their base class
# methods.

from notebook.utils import url_path_join as ujoin

from .envmanager import EnvManager
from .apihandlers import *

NS = r'api/packagemanager'


# -----------------------------------------------------------------------------
# URL to handler mappings
# -----------------------------------------------------------------------------


default_handlers = [
    (r"/projects", ManageProjectsHandler),
    (r"/project_info", ProjectInfoHandler),
    (r"/packages", PkgHandler),
    (r"/packages/check_update", CheckUpdatePkgHandler),
    (r"/packages/available", AvailablePackagesHandler),
    (r"/packages/search", SearchHandler),
    (r"/project_clone", CloneProjectHandler),
]


def load_jupyter_server_extension(nb_server_app):
    '''
    Load the nbserver extension
    '''

    webapp = nb_server_app.web_app
    webapp.settings['env_manager'] = EnvManager(parent=nb_server_app)

    base_url = webapp.settings['base_url']
    webapp.add_handlers(".*$", [
        (ujoin(base_url, NS, pat), handler)
        for pat, handler in default_handlers
    ])
    nb_server_app.log.info("packagemanagerextension: Handlers enabled")
