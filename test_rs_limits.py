# Copyright 2012 Rackspace
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import StringIO
import sys

import mock
from turnstile import config
from turnstile import tools
import unittest2

import rs_limits


class TestPreprocess(unittest2.TestCase):
    def test_nogroups(self):
        db = mock.Mock(**{'get.return_value': None})
        midware = mock.Mock(db=db)
        environ = {}

        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ, {})
        self.assertFalse(db.get.called)

    def test_group_order(self):
        db = mock.Mock(**{'get.return_value': None})
        midware = mock.Mock(db=db)
        environ = dict(
            HTTP_X_PP_GROUPS='grp1,grp2;q=0.5,grp3;q=0.7, grp4;q=0.9,grp5',
        )

        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ, dict(
            HTTP_X_PP_GROUPS='grp1,grp2;q=0.5,grp3;q=0.7, grp4;q=0.9,grp5',
        ))
        db.assert_has_calls([
            mock.call.get('rs-group:grp1'),
            mock.call.get('rs-group:grp5'),
            mock.call.get('rs-group:grp4'),
            mock.call.get('rs-group:grp3'),
            mock.call.get('rs-group:grp2'),
        ])

    def test_group_badqual(self):
        db = mock.Mock(**{'get.return_value': None})
        midware = mock.Mock(db=db)
        environ = dict(
            HTTP_X_PP_GROUPS='grp1;q=0.1,grp2;f=a;q=0.5,grp3;q=0.6a,'
                             'grp4;f=0.7',
        )

        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ, dict(
            HTTP_X_PP_GROUPS='grp1;q=0.1,grp2;f=a;q=0.5,grp3;q=0.6a,'
                             'grp4;f=0.7',
        ))
        db.assert_has_calls([
            mock.call.get('rs-group:grp2'),
            mock.call.get('rs-group:grp3'),
            mock.call.get('rs-group:grp4'),
            mock.call.get('rs-group:grp1'),
        ])

    def test_group_select(self):
        classes = {'rs-group:grp3': 'lim_class'}
        db = mock.Mock(**{'get.side_effect': lambda x: classes.get(x)})
        midware = mock.Mock(db=db)
        environ = dict(
            HTTP_X_PP_GROUPS='grp1,grp2,grp3,grp4,grp5',
        )

        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ, {
            'HTTP_X_PP_GROUPS': 'grp1,grp2,grp3,grp4,grp5',
            'turnstile.nova.limitclass': 'lim_class',
        })
        db.assert_has_calls([
            mock.call.get('rs-group:grp1'),
            mock.call.get('rs-group:grp2'),
            mock.call.get('rs-group:grp3'),
        ])

    def test_group_context_no_quota_class(self):
        classes = {'rs-group:grp3': 'lim_class'}
        db = mock.Mock(**{'get.side_effect': lambda x: classes.get(x)})
        midware = mock.Mock(db=db)
        context = mock.Mock(spec=[])
        environ = {
            'HTTP_X_PP_GROUPS': 'grp1,grp2,grp3,grp4,grp5',
            'nova.context': context,
        }

        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ['turnstile.nova.limitclass'], 'lim_class')
        db.assert_has_calls([
            mock.call.get('rs-group:grp1'),
            mock.call.get('rs-group:grp2'),
            mock.call.get('rs-group:grp3'),
        ])
        self.assertFalse(hasattr(context, 'quota_class'))

    def test_group_context(self):
        classes = {'rs-group:grp3': 'lim_class'}
        db = mock.Mock(**{'get.side_effect': lambda x: classes.get(x)})
        midware = mock.Mock(db=db)
        context = mock.Mock(quota_class=None, spec=['quota_class'])
        environ = {
            'HTTP_X_PP_GROUPS': 'grp1,grp2,grp3,grp4,grp5',
            'nova.context': context,
        }

        rs_limits.rs_preprocess(midware, environ)

        self.assertEqual(environ['turnstile.nova.limitclass'], 'lim_class')
        db.assert_has_calls([
            mock.call.get('rs-group:grp1'),
            mock.call.get('rs-group:grp2'),
            mock.call.get('rs-group:grp3'),
        ])
        self.assertEqual(context.quota_class, 'lim_class')


class TestCheckArguments(unittest2.TestCase):
    def test_neither(self):
        args = mock.Mock(klass=None, delete=False)

        # Checking that no exceptions are raised
        rs_limits._check_arguments(args)

    def test_klass_only(self):
        args = mock.Mock(klass='class', delete=False)

        # Checking that no exceptions are raised
        rs_limits._check_arguments(args)

    def test_delete_only(self):
        args = mock.Mock(klass=None, delete=True)

        # Checking that no exceptions are raised
        rs_limits._check_arguments(args)

    def test_both(self):
        args = mock.Mock(klass='class', delete=True)

        self.assertRaises(Exception, rs_limits._check_arguments, args)


class TestReportGroupClass(unittest2.TestCase):
    @mock.patch.object(sys, 'stdout', StringIO.StringIO())
    def test_unconfigured(self):
        args = mock.Mock(group='group', klass=None, delete=False)

        result = rs_limits._report_group_class(args, None)

        self.assertEqual(result, None)
        self.assertEqual(sys.stdout.getvalue(),
                         "Group group:\n"
                         "  Not currently configured in database.\n")

    @mock.patch.object(sys, 'stdout', StringIO.StringIO())
    def test_configured(self):
        args = mock.Mock(group='group', klass=None, delete=False)

        result = rs_limits._report_group_class(args, 'old_class')

        self.assertEqual(result, None)
        self.assertEqual(sys.stdout.getvalue(),
                         "Group group:\n"
                         "  Configured rate-limit class: old_class\n")

    @mock.patch.object(sys, 'stdout', StringIO.StringIO())
    def test_deleted_unconfigured(self):
        args = mock.Mock(group='group', klass=None, delete=True)

        result = rs_limits._report_group_class(args, None)

        self.assertEqual(result, None)
        self.assertEqual(sys.stdout.getvalue(),
                         "Group group:\n"
                         "  Deleted from database\n")

    @mock.patch.object(sys, 'stdout', StringIO.StringIO())
    def test_deleted(self):
        args = mock.Mock(group='group', klass=None, delete=True)

        result = rs_limits._report_group_class(args, 'old_class')

        self.assertEqual(result, None)
        self.assertEqual(sys.stdout.getvalue(),
                         "Group group:\n"
                         "  Previous rate-limit class: old_class\n"
                         "  Deleted from database\n")

    @mock.patch.object(sys, 'stdout', StringIO.StringIO())
    def test_updated_unconfigured(self):
        args = mock.Mock(group='group', klass='new_class', delete=False)

        result = rs_limits._report_group_class(args, None)

        self.assertEqual(result, None)
        self.assertEqual(sys.stdout.getvalue(),
                         "Group group:\n"
                         "  New rate-limit class: new_class\n")

    @mock.patch.object(sys, 'stdout', StringIO.StringIO())
    def test_updated(self):
        args = mock.Mock(group='group', klass='new_class', delete=False)

        result = rs_limits._report_group_class(args, 'old_class')

        self.assertEqual(result, None)
        self.assertEqual(sys.stdout.getvalue(),
                         "Group group:\n"
                         "  Previous rate-limit class: old_class\n"
                         "  New rate-limit class: new_class\n")


class TestGroupClass(unittest2.TestCase):
    def test_has_arguments(self):
        self.assertIsInstance(rs_limits.group_class, tools.ScriptAdaptor)
        self.assertGreater(len(rs_limits.group_class._arguments), 0)

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': 'old_class',
        }),
    }))
    def test_get(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = rs_limits.group_class('config_file', 'spam')

        self.assertEqual(result, 'old_class')
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('rs-group:spam')
        self.assertFalse(db.set.called)
        self.assertFalse(db.delete.called)

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': None,
        }),
    }))
    def test_get_unset(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = rs_limits.group_class('config_file', 'spam')

        self.assertEqual(result, None)
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('rs-group:spam')
        self.assertFalse(db.set.called)
        self.assertFalse(db.delete.called)

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': 'old_class',
        }),
    }))
    def test_set(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = rs_limits.group_class('config_file', 'spam',
                                       klass='new_class')

        self.assertEqual(result, 'old_class')
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('rs-group:spam')
        db.set.assert_called_once_with('rs-group:spam', 'new_class')
        self.assertFalse(db.delete.called)

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': None,
        }),
    }))
    def test_set_unset(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = rs_limits.group_class('config_file', 'spam',
                                       klass='new_class')

        self.assertEqual(result, None)
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('rs-group:spam')
        db.set.assert_called_once_with('rs-group:spam', 'new_class')
        self.assertFalse(db.delete.called)

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': 'old_class',
        }),
    }))
    def test_delete(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = rs_limits.group_class('config_file', 'spam', delete=True)

        self.assertEqual(result, 'old_class')
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('rs-group:spam')
        self.assertFalse(db.set.called)
        db.delete.assert_called_once_with('rs-group:spam')

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': None,
        }),
    }))
    def test_delete_unset(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = rs_limits.group_class('config_file', 'spam', delete=True)

        self.assertEqual(result, None)
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('rs-group:spam')
        self.assertFalse(db.set.called)
        self.assertFalse(db.delete.called)
