import os


class locator:
    def __init__(self):
        pass

    def isDev(self):
        return not self.isProd()

    def isProd(self):
        return os.getenv('PRODUCTION', '').lower() == 'true'

    def database_url(self):
        database_url = os.getenv('COUCH_DATABASE_URL')
        if database_url:
            return database_url
        if self.isDev():
            return 'http://vocms0485.cern.ch:5984/'  # dev instance
        else:
            return 'http://vocms0490.cern.ch:5984/'  # prod instance

    def lucene_url(self):
        lucene_url = os.getenv('LUCENE_URL')
        if lucene_url:
            return lucene_url
        if self.isDev():
            return 'http://vocms0485.cern.ch:5985/'  # dev instance
        else:
            return 'http://vocms0490.cern.ch:5985/'  # prod instance

    def workLocation(self):
        if self.isDev():
            return '/afs/cern.ch/cms/PPD/PdmV/work/McM/dev-submit/'
        else:
            return '/afs/cern.ch/cms/PPD/PdmV/work/McM/submit/'

    def baseurl(self):
        base_url = os.getenv('BASE_URL')
        if base_url:
            return base_url
        if self.isDev():
            return 'https://cms-pdmv-dev.cern.ch/mcm/'
        else:
            return 'https://cms-pdmv.cern.ch/mcm/'

    def cmsweburl(self):
        if self.isDev():
            return 'https://cmsweb-testbed.cern.ch/'
        else:
            return 'https://cmsweb.cern.ch/'
