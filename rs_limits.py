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

import argparse
from turnstile import config


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


def _group_class(conf_file, group, klass=None, delete=False):
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
    if delete:
        db.delete(key)
    elif klass and klass != old_klass:
        db.set(key, klass)

    return old_klass


def group_class():
    """
    Console script entry point for setting limit classes associated
    with particular groups.
    """

    parser = argparse.ArgumentParser(
        description="Set up or query limit classes associated with groups.",
        )

    parser.add_argument('config',
                        help="Name of the configuration file, for connecting "
                        "to the Redis database.")
    parser.add_argument('group',
                        help="Name of the group.")
    parser.add_argument('--debug', '-d',
                        dest='debug',
                        action='store_true',
                        default=False,
                        help="Run the tool in debug mode.")
    parser.add_argument('--delete', '-D',
                        dest='delete',
                        action='store_true',
                        default=False,
                        help="Delete the group from the database.")
    parser.add_argument('--class', '-c',
                        dest='klass',
                        action='store',
                        default=None,
                        help="If specified, sets the class associated with "
                        "the given group.")

    args = parser.parse_args()

    # Don't allow --class and --delete to both be given
    if args.klass and args.delete:
        return "The --class and --delete options are mutually exclusive."

    try:
        klass = _group_class(args.config, args.group, args.klass, args.delete)

        print "Group %s:" % args.group
        if args.klass or args.delete:
            if klass:
                print "  Previous rate-limit class: %s" % klass
            if args.delete:
                print "  Deleted from database"
            else:
                print "  New rate-limit class: %s" % args.klass
        elif klass:
            print "  Configured rate-limit class: %s" % klass
        else:
            print "  Not currently configured in database."
    except Exception as exc:
        if args.debug:
            raise
        return str(exc)
