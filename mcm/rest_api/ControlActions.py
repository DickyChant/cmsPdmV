import flask
from RestAPIMethod import RESTResource
from json_layer.user import User
from tools.settings import Settings
from couchdb_layer.mcm_database import database as Database
from tools.utils import clean_split


class Search(RESTResource):
    """
    Super-generic search through database (uses __all__ attribute in __init__.py of json_layer package)
    """

    modules = {'batches': 'batch',
               'campaigns': 'campaign',
               'chained_campaigns': 'chained_campaign',
               'chained_requests': 'chained_request',
               'flows': 'flow',
               'invalidations': 'invalidation',
               'mccms': 'mccm',
               'requests': 'request',
               'settings': 'setting',
               'users': 'user'}
    casting = None

    @classmethod
    def prepare_casting(cls):
        cls.logger.info('Preparing attribute casting in search')
        import json_layer
        cls.casting = {}
        for database_name, module_name in cls.modules.items():
            module = getattr(json_layer, module_name)
            class_obj = getattr(module, module_name)
            schema = class_obj.class_schema()
            if not schema:
                continue

            cls.casting[database_name] = {}
            for schema_key, schema_value in schema.items():
                schema_type = type(schema_value)
                if schema_type in [int, float]:
                    cls.casting[database_name][schema_key] = '%s<%s>' % (schema_key,
                                                                         schema_type.__name__)

    def __init__(self):
        if not self.casting:
            self.prepare_casting()

    def get(self):
        args = flask.request.args.to_dict()
        self.logger.debug('Search: %s', ','.join('%s=%s' % (k, v) for k, v in args.items()))
        db_name = args.pop('db_name', 'requests')
        page = int(args.pop('page', 0))
        limit = int(args.pop('limit', 20))
        include_fields = args.pop('include_fields', '')
        sort_on = args.pop('sort', None)
        sort_asc = args.pop('sort_asc', 'True').lower() != 'false'
        # Drop get_raw attribute
        args.pop('get_raw', None)
        # Drio alias attribute
        args.pop('alias', None)

        if db_name not in self.modules:
            return {'results': False, 'message': 'Invalid database name %s' % (db_name)}

        if page == -1 and not args and db_name == 'requests':
            return {"results": False, "message": "Why you stupid? Don't be stupid..."}

        database = Database(db_name)
        args = {k: clean_split(v) if k != 'range' else v for k, v in args.items()}
        # range - requests, chained_requests, tickets
        get_range  = args.pop('range', None)
        if get_range and db_name in ('requests', 'chained_requests', 'tickets'):
            # Get range of objects
            # Syntax: a,b;c,d;e;f
            args['prepid_'] = []
            for part in clean_split(get_range, ';'):
                if ',' in part:
                    parts = part.split(',')
                    start = parts[0].split('-')
                    end = parts[1].split('-')
                    numbers = range(int(start[-1]), int(end[-1]) + 1)
                    start = '-'.join(start[:-1])
                    args['prepid_'].extend('%s-%05d' % (start, n) for n in numbers)
                else:
                    args['prepid_'].append(part)

        # from_ticket - chained_requests
        from_ticket = args.pop('from_ticket', None)
        if from_ticket and db_name in ('chained_requests', ):
            # Get chained requests generated from the ticket
            mccm_db = Database('mccms')
            if len(from_ticket) == 1 and '*' not in from_ticket[0]:
                mccms = [mccm_db.get(from_ticket[0])]
            else:
                mccms = mccm_db.search({'prepid': from_ticket}, page=-1)

            args['prepid__'] = []
            for mccm in mccms:
                args['prepid__'].extend(mccm.get('generated_chains', []).keys())

        if not args and not sort_on:
            # If there are no args, use simpler fetch
            res = database.get_all(page, limit, with_total_rows=True)
        else:
            # Add types to arguments
            args = {self.casting[db_name].get(k, k): v for k, v in args.items()}
            # Construct the complex query
            res = database.search(args, page, limit, include_fields, True, sort_on, sort_asc)

        res['results'] = res.pop('rows', [])
        return self.output_text(res, 200, {'Content-Type': 'application/json'})


class CacheClear(RESTResource):

    def get(self):
        """
        Clear McM cache
        """
        Database.clear_cache()
        Settings.clear_cache()
        User.clear_cache()
        return {'results': True}
