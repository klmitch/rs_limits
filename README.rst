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

The ``rs_limits.rs_preprocess()`` preprocessor derives the rate-limit
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

Repose Group Priority Bug
=========================

Repose places groups in the "X-PP-Groups" header, giving them all a
quality factor.  Unfortunately, at least some versions of Repose
hard-code this quality factor, making it difficult to determine which
group should be given priority in the rate limit class selection
algorithm.  To work around this, the ``rs_limits.rs_preprocess()``
function allows group priorities to be set using a Turnstile
configuration option.  These priorities are only used if all groups in
the "X-PP-Groups" header have a quality factor of 1.0.

The configuration option to use is ``rs_limits.groups``.  The value
for this option is a comma-separated list of "key=value" pairs, where
the "key" is the name of a group, and the "value" is a float in the
interval [0.0, 1.0].  If a group is specified in "X-PP-Groups" which
does not exist in this list of groups, it will be given a default
priority of 0.1.  This default value can be altered by specifying an
entry without a key; e.g., to specify a default priority of 0.05, use
"=0.05" in the groups list.

Note that, when using this built-in group priority system, group names
are considered in a case insensitive manner.  The case used in the
"X-PP-Groups" header will, however, be preserved.
