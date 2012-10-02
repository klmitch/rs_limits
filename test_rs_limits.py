import StringIO
import sys

import argparse
import stubout
from turnstile import config
import unittest2

import rs_limits


class FakeDatabase(object):
    def __init__(self, fake_db=None):
        self.fake_db = fake_db or {}
        self.actions = []

    def get(self, key):
        self.actions.append(('get', key))
        return self.fake_db.get(key)

    def set(self, key, value):
        self.actions.append(('set', key, value))
        self.fake_db[key] = value

    def delete(self, key):
        self.actions.append(('delete', key))
        if key in self.fake_db:
            del self.fake_db[key]


class FakeMiddleware(object):
    def __init__(self, db):
        self.db = db


class FakeContext(object):
    def __init__(self, setup_quota_class=False):
        if setup_quota_class:
            self.quota_class = None


class TestPreprocess(unittest2.TestCase):
    def test_nogroups(self):
        db = FakeDatabase()
        midware = FakeMiddleware(db)
        environ = {}
        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ, {})
        self.assertEqual(db.actions, [])

    def test_group_order(self):
        db = FakeDatabase()
        midware = FakeMiddleware(db)
        environ = dict(
            HTTP_X_PP_GROUPS='grp1,grp2;q=0.5,grp3;q=0.7, grp4;q=0.9,grp5',
            )
        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ, dict(
                HTTP_X_PP_GROUPS='grp1,grp2;q=0.5,grp3;q=0.7, grp4;q=0.9,grp5',
                ))
        self.assertEqual(db.actions, [
                ('get', 'rs-group:grp1'),
                ('get', 'rs-group:grp5'),
                ('get', 'rs-group:grp4'),
                ('get', 'rs-group:grp3'),
                ('get', 'rs-group:grp2'),
                ])

    def test_group_badqual(self):
        db = FakeDatabase()
        midware = FakeMiddleware(db)
        environ = dict(
            HTTP_X_PP_GROUPS=('grp1;q=0.1,grp2;f=a;q=0.5,grp3;q=0.6a,'
                              'grp4;f=0.7'),
            )
        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ, dict(
                HTTP_X_PP_GROUPS=('grp1;q=0.1,grp2;f=a;q=0.5,grp3;q=0.6a,'
                                  'grp4;f=0.7'),
                ))
        self.assertEqual(db.actions, [
                ('get', 'rs-group:grp2'),
                ('get', 'rs-group:grp3'),
                ('get', 'rs-group:grp4'),
                ('get', 'rs-group:grp1'),
                ])

    def test_group_select(self):
        db = FakeDatabase({'rs-group:grp3': 'lim_class'})
        midware = FakeMiddleware(db)
        environ = dict(
            HTTP_X_PP_GROUPS='grp1,grp2,grp3,grp4,grp5',
            )
        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ, {
                'HTTP_X_PP_GROUPS': 'grp1,grp2,grp3,grp4,grp5',
                'turnstile.nova.limitclass': 'lim_class',
                })
        self.assertEqual(db.actions, [
                ('get', 'rs-group:grp1'),
                ('get', 'rs-group:grp2'),
                ('get', 'rs-group:grp3'),
                ])

    def test_group_context_no_quota_class(self):
        db = FakeDatabase({'rs-group:grp3': 'lim_class'})
        midware = FakeMiddleware(db)
        context = FakeContext()
        environ = {
            'HTTP_X_PP_GROUPS': 'grp1,grp2,grp3,grp4,grp5',
            'nova.context': context,
            }
        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ['turnstile.nova.limitclass'], 'lim_class')
        self.assertEqual(db.actions, [
                ('get', 'rs-group:grp1'),
                ('get', 'rs-group:grp2'),
                ('get', 'rs-group:grp3'),
                ])
        self.assertFalse(hasattr(context, 'quota_class'))

    def test_group_context(self):
        db = FakeDatabase({'rs-group:grp3': 'lim_class'})
        midware = FakeMiddleware(db)
        context = FakeContext(True)
        environ = {
            'HTTP_X_PP_GROUPS': 'grp1,grp2,grp3,grp4,grp5',
            'nova.context': context,
            }
        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ['turnstile.nova.limitclass'], 'lim_class')
        self.assertEqual(db.actions, [
                ('get', 'rs-group:grp1'),
                ('get', 'rs-group:grp2'),
                ('get', 'rs-group:grp3'),
                ])
        self.assertTrue(hasattr(context, 'quota_class'))
        self.assertEqual(context.quota_class, 'lim_class')


class TestGroupClass(unittest2.TestCase):
    def setUp(self):
        self.fake_db = FakeDatabase()
        self.stubs = stubout.StubOutForTesting()

        class FakeConfig(object):
            def __init__(inst, conf_file=None):
                self.assertEqual(conf_file, 'config_file')

            def get_database(inst):
                return self.fake_db

        self.stubs.Set(config, 'Config', FakeConfig)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_get(self):
        self.fake_db.fake_db['rs-group:grp1'] = 'lim_class'
        old_klass = rs_limits._group_class('config_file', 'grp1')

        self.assertEqual(self.fake_db.fake_db, {
                'rs-group:grp1': 'lim_class',
                })
        self.assertEqual(self.fake_db.actions, [
                ('get', 'rs-group:grp1'),
                ])
        self.assertEqual(old_klass, 'lim_class')

    def test_get_undeclared(self):
        old_klass = rs_limits._group_class('config_file', 'grp1')

        self.assertEqual(self.fake_db.fake_db, {})
        self.assertEqual(self.fake_db.actions, [
                ('get', 'rs-group:grp1'),
                ])
        self.assertEqual(old_klass, None)

    def test_set(self):
        self.fake_db.fake_db['rs-group:grp1'] = 'old_class'
        old_klass = rs_limits._group_class('config_file', 'grp1',
                                           klass='new_class')

        self.assertEqual(self.fake_db.fake_db, {
                'rs-group:grp1': 'new_class',
                })
        self.assertEqual(self.fake_db.actions, [
                ('get', 'rs-group:grp1'),
                ('set', 'rs-group:grp1', 'new_class'),
                ])
        self.assertEqual(old_klass, 'old_class')

    def test_set_undeclared(self):
        old_klass = rs_limits._group_class('config_file', 'grp1',
                                           klass='new_class')

        self.assertEqual(self.fake_db.fake_db, {
                'rs-group:grp1': 'new_class',
                })
        self.assertEqual(self.fake_db.actions, [
                ('get', 'rs-group:grp1'),
                ('set', 'rs-group:grp1', 'new_class'),
                ])
        self.assertEqual(old_klass, None)

    def test_set_unchanged(self):
        self.fake_db.fake_db['rs-group:grp1'] = 'lim_class'
        old_klass = rs_limits._group_class('config_file', 'grp1',
                                           klass='lim_class')

        self.assertEqual(self.fake_db.fake_db, {
                'rs-group:grp1': 'lim_class',
                })
        self.assertEqual(self.fake_db.actions, [
                ('get', 'rs-group:grp1'),
                ])
        self.assertEqual(old_klass, 'lim_class')

    def test_delete(self):
        self.fake_db.fake_db['rs-group:grp1'] = 'old_class'
        old_klass = rs_limits._group_class('config_file', 'grp1', delete=True)

        self.assertEqual(self.fake_db.fake_db, {})
        self.assertEqual(self.fake_db.actions, [
                ('get', 'rs-group:grp1'),
                ('delete', 'rs-group:grp1'),
                ])
        self.assertEqual(old_klass, 'old_class')

    def test_delete_undeclared(self):
        old_klass = rs_limits._group_class('config_file', 'grp1', delete=True)

        self.assertEqual(self.fake_db.fake_db, {})
        self.assertEqual(self.fake_db.actions, [
                ('get', 'rs-group:grp1'),
                ('delete', 'rs-group:grp1'),
                ])
        self.assertEqual(old_klass, None)


class FakeNamespace(object):
    config = 'config'
    group = 'grp1'
    debug = False
    delete = False
    klass = None

    def __init__(self, nsdict):
        self.__dict__.update(nsdict)


class FakeArgumentParser(object):
    def __init__(self, nsdict):
        self._namespace = FakeNamespace(nsdict)

    def add_argument(self, *args, **kwargs):
        pass

    def parse_args(self):
        return self._namespace


class TestToolGroupClass(unittest2.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()

        self.group_class_result = None
        self.group_class_args = None

        self.args_dict = {}

        self.stdout = StringIO.StringIO()

        def fake_group_class(config, group, klass=None, delete=False):
            self.group_class_args = (config, group, klass, delete)
            if isinstance(self.group_class_result, Exception):
                raise self.group_class_result
            return self.group_class_result

        def fake_argument_parser(*args, **kwargs):
            return FakeArgumentParser(self.args_dict)

        self.stubs.Set(rs_limits, '_group_class', fake_group_class)
        self.stubs.Set(argparse, 'ArgumentParser', fake_argument_parser)
        self.stubs.Set(sys, 'stdout', self.stdout)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_noargs(self):
        result = rs_limits.group_class()

        self.assertEqual(self.group_class_args,
                         ('config', 'grp1', None, False))
        self.assertEqual(self.stdout.getvalue(),
                         'Group grp1:\n'
                         '  Not currently configured in database.\n')
        self.assertEqual(result, None)

    def test_failure(self):
        self.group_class_result = Exception("foobar")
        result = rs_limits.group_class()

        self.assertEqual(result, "foobar")
        self.assertEqual(self.stdout.getvalue(), '')

    def test_failure_debug(self):
        class AnException(Exception):
            pass

        self.args_dict['debug'] = True
        self.group_class_result = AnException("foobar")
        with self.assertRaises(AnException):
            rs_limits.group_class()
        self.assertEqual(self.stdout.getvalue(), '')

    def test_report(self):
        self.group_class_result = 'old_class'
        rs_limits.group_class()

        self.assertEqual(self.group_class_args,
                         ('config', 'grp1', None, False))
        self.assertEqual(self.stdout.getvalue(),
                         'Group grp1:\n'
                         '  Configured rate-limit class: old_class\n')

    def test_update(self):
        self.args_dict['klass'] = 'new_class'
        self.group_class_result = 'old_class'
        rs_limits.group_class()

        self.assertEqual(self.group_class_args,
                         ('config', 'grp1', 'new_class', False))
        self.assertEqual(self.stdout.getvalue(),
                         'Group grp1:\n'
                         '  Previous rate-limit class: old_class\n'
                         '  New rate-limit class: new_class\n')

    def test_update_undefined(self):
        self.args_dict['klass'] = 'new_class'
        rs_limits.group_class()

        self.assertEqual(self.group_class_args,
                         ('config', 'grp1', 'new_class', False))
        self.assertEqual(self.stdout.getvalue(),
                         'Group grp1:\n'
                         '  New rate-limit class: new_class\n')

    def test_delete(self):
        self.args_dict['delete'] = True
        self.group_class_result = 'old_class'
        rs_limits.group_class()

        self.assertEqual(self.group_class_args,
                         ('config', 'grp1', None, True))
        self.assertEqual(self.stdout.getvalue(),
                         'Group grp1:\n'
                         '  Previous rate-limit class: old_class\n'
                         '  Deleted from database\n')

    def test_delete_undefined(self):
        self.args_dict['delete'] = True
        rs_limits.group_class()

        self.assertEqual(self.group_class_args,
                         ('config', 'grp1', None, True))
        self.assertEqual(self.stdout.getvalue(),
                         'Group grp1:\n'
                         '  Deleted from database\n')

    def test_update_delete(self):
        self.args_dict['klass'] = 'new_class'
        self.args_dict['delete'] = True
        result = rs_limits.group_class()

        self.assertEqual(result,
                         'The --class and --delete options are '
                         'mutually exclusive.')
