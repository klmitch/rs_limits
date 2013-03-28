========================================================
Rackspace-specific Rate Limit Preprocessor for Turnstile
========================================================

This package provides the ``rs_limits`` Python module, which contains
the ``rs_preprocess()`` preprocessor for use with Turnstile.  This
module works together with nova_limits to provide class-based rate
limiting integration with nova in the Rackspace.  To use, you must
configure the Turnstile middleware with the following configuration::

    [filter:turnstile]
    use = egg:turnstile#turnstile
    enable = rs_limits nova_limits
    formatter = nova_limits
    redis.host = <your Redis database host>

Then, simply use the ``nova_limits`` rate limit class in your limits
configuration.

The ``rs_limits:rs_preprocess()`` preprocessor derives the rate-limit
class from the "X-PP-Groups" header of the request, if present.  It
expects the database to contain a key "rs-group:<group name>" mapping
the group name to a rate-limit class; if no such key exists, the next
group name will be tried.

Note that ``rs_limits`` must be listed in the ``enable`` key of the
configuration immediately before ``nova_limits``.

Mapping Groups to Rate Limit Classes
====================================

A ``group_class`` command is provided to control the mapping of the
group to the rate limit class.  A usage summary follows::

    usage: group_class [-h] [--debug] [--delete] [--class KLASS] config group

    Set up or query limit classes associated with groups.

    positional arguments:
      config                Name of the configuration file, for connecting to the
                            Redis database.
      group                 Name of the group.

    optional arguments:
      -h, --help            show this help message and exit
      --debug, -d           Run the tool in debug mode.
      --delete, -D          Delete the group from the database.
      --class KLASS, -c KLASS
                            If specified, sets the class associated with the given
                            group.
