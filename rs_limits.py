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

from turnstile import config
from turnstile import tools


class GroupPriorities(dict):
    """
    Map groups to priorities.
    """

    def __init__(self, conf_value):
        """
        Initialize the priorities from the configuration value, which
        is a string looking like:

            =0.1,Admin=0.5,Delinquent=1.0

        An empty group name will become the default value for all
        groups; if it's not specificed, the value used will be 0.1.
        The priority value may range between 0 and 1, and will be
        clamped to those values; it will also be capped at 3 decimal
        places, to comply with the HTTP spec for quality values.

        Note: Group names are coerced to lower-case for case
        insensitivity.

        :param conf_value: The configuration value, as described
                           above.
        """

        # Initialize the dict object
        super(GroupPriorities, self).__init__()

        # Now, start populating ourself
        for group_spec in conf_value.split(','):
            group_spec = group_spec.strip()
            group, _sep, prio = group_spec.partition('=')

            group = group.strip()
            try:
                prio = float(prio)
            except ValueError:
                # We'll use the default value for this group
                continue

            self[group.lower()] = prio

    def __missing__(self, key):
        """
        Retrieve a default value for the priority of an undeclared
        group.

        :param key: The name of the undeclared group.
        """

        return self.get('', 0.1)


def rs_preprocess(midware, environ):
    """
    Pre-process requests to nova.  Derives the rate-limit class from
    the X-PP-Groups header.
    """

    # If we don't have the header, let nova_preprocess() do its magic.
    group_str = environ.get('HTTP_X_PP_GROUPS')
    if not group_str:
        return

    # We'll need the nova context
    context = environ.get('nova.context')
    if context and not hasattr(context, 'quota_class'):
        # If the context doesn't have quota_class, then don't activate
        # the quota_class part of the algorithm...
        context = None

    # Split the groups string into a list of groups, respecting quality
    groups = []
    overall_quality = 1.0
    for group in group_str.split(','):
        # Strip off any whitespace, just in case
        group = group.strip()

        # Convert quality, if present
        quality = 1.0
        name, _sep, qual_str = group.partition(';')
        if qual_str.startswith('q='):
            try:
                quality = float(qual_str[2:])
            except ValueError:
                # Invalid float; use 1.0
                pass

        groups.append((name, quality))
        overall_quality *= quality

    # If the overall quality is 1.0, that means we have the Repose
    # group priority bug; work around it by rebuilding the groups list
    if overall_quality == 1.0:
        # First, let's build the group priorities dictionary
        conf = environ.get('turnstile.conf', {'rs_limits': {}})
        prios = GroupPriorities(conf['rs_limits'].get('groups', ''))

        # Now walk through the groups list and rebuild it
        for idx in range(len(groups)):
            name, quality = groups[idx]
            groups[idx] = (name, prios[name.lower()] * quality)

    # Look up the rate-limit class from the database
    for group, _quality in sorted(groups, key=lambda x: x[1], reverse=True):
        klass = midware.db.get('rs-group:%s' % group)
        if klass:
            # We have our rate-limit group!
            environ['turnstile.nova.limitclass'] = klass

            # If we have a context that supports it, set the quota
            # class
            if context:
                context.quota_class = klass

            return


def _check_arguments(args):
    """
    Sanity-check the arguments to ensure that the --class and --delete
    options are not both given.  This is a preprocessor for the
    group_class() function, when being called in console script mode.

    :param args: A Namespace object containing a 'klass' attribute and
                 a 'delete' attribute.
    """

    if args.klass and args.delete:
        raise Exception("The --class and --delete options are "
                        "mutually exclusive.")


def _report_group_class(args, result):
    """
    Report the rate-limit class for the group.  This is a
    postprocessor for the group_class() function, when being called in
    console script mode.

    :param args: A Namespace object containing a 'group' attribute, a
                 desired rate-limit class in the 'klass' attribute
                 (which should be None if no change was requested),
                 and a 'delete' attribute (which should be True if the
                 association was to be deleted).
    :param result: The result of the group_class() function call.
                   This will be the previously configured rate-limit
                   class for the group.

    :returns: None to indicate success.
    """

    print "Group %s:" % args.group
    if args.klass or args.delete:
        if result:
            print "  Previous rate-limit class: %s" % result
        if args.delete:
            print "  Deleted from database"
        else:
            print "  New rate-limit class: %s" % args.klass
    elif result:
        print "  Configured rate-limit class: %s" % result
    else:
        print "  Not currently configured in database."

    return None


@tools.add_argument('config',
                    help="Name of the configuration file, for connecting "
                    "to the Redis database.")
@tools.add_argument('group',
                    help="Name of the group.")
@tools.add_argument('--debug', '-d',
                    dest='debug',
                    action='store_true',
                    default=False,
                    help="Run the tool in debug mode.")
@tools.add_argument('--delete', '-D',
                    dest='delete',
                    action='store_true',
                    default=False,
                    help="Delete the group from the database.")
@tools.add_argument('--class', '-c',
                    dest='klass',
                    action='store',
                    default=None,
                    help="If specified, sets the class associated with "
                    "the given group.")
@tools.add_preprocessor(_check_arguments)
@tools.add_postprocessor(_report_group_class)
def group_class(conf_file, group, klass=None, delete=False):
    """
    Set up or query limit classes associated with groups.

    :param conf_file: Name of the configuration file, for connecting
                      to the Redis database.
    :param group: The name of the group.
    :param klass: If provided, the name of the class to map the group
                  to.
    :param delete: If True, deletes the group from the database.

    Returns the class associated with the given group.  Note that only
    one of `klass` or `delete` may be given.
    """

    # Connect to the database...
    conf = config.Config(conf_file=conf_file)
    db = conf.get_database()

    # Get the key for the limit class...
    key = 'rs-group:%s' % group

    # Now, look up the tenant's current class
    old_klass = db.get(key)

    # Do we need to delete it?  Change it?
    if delete and old_klass is not None:
        db.delete(key)
    elif klass and klass != old_klass:
        db.set(key, klass)

    return old_klass


# For backwards compatibility
_group_class = group_class
