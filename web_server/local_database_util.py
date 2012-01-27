# -*- coding: utf-8 -*-
"""
local_database_util.py

utility routines for the node local database
"""

from tools.data_definitions import conjoined_row_template, segment_row_template

def current_status_of_key(connection, collection_id, key, version_id):
    """
    retrieve the conjoined row (if any) and all related
    segment_rows for this key

    return a tuple of (conjoined_row, [segment_rows])
    """
    # get the conjoined_row, if any
    result = connection.fetch_one_row("""
        select %s from nimbusio_node.conjoined 
        where collection_id = %%s and key = %%s
        order by create_timestamp desc
        limit 1
    """ % (",".join(conjoined_row_template._fields), ), [collection_id, key, ])

    conjoined_row = (
        None if  result is None else conjoined_row_template._make(result)
    )

    segment_rows = []
    if conjoined_row is None:
        # if we don't have a conjoined row, 
        #    if version_id is not None:
        #       get the row with an exact match on version_id (if any)
        #    otherwise:
        #       get the most recent segment row (if any)
        if version_id is not None:
            result = connection.fetch_one_row("""
                select %s from nimbusio_node.segment 
                where unified_id = %%s
                and handoff_node_id is null
            """ % (",".join(segment_row_template._fields), ), 
            [version_id, ])
        else:
            result = connection.fetch_one_row("""
                select %s from nimbusio_node.segment 
                where collection_id = %%s 
                and key = %%s 
                and handoff_node_id is null
                order by timestamp desc
                limit 1
            """ % (",".join(segment_row_template._fields), ), 
            [collection_id, key, ])

        if result is not None:
            segment_rows = [segment_row_template._make(result), ]

    else:
        # otherwise, get all the conjoined rows for the identifier,
        # ordered by conjoined_part

        result = connection.fetch_all_rows("""
            select %s from nimbusio_node.segment 
            where conjoined_unified_id = %%s 
            order by conjoined_part
        """ % (",".join(segment_row_template._fields), ), 
        [conjoined_row.unified_id, ])

        segment_rows = [segment_row_template._make(r) for r in result]

    return (conjoined_row, segment_rows, )

