# coding=utf-8
"""
Utility functions for Kata.
"""

import logging
import urllib2
import socket
import functionally as fn

from lxml import etree
import re
from sqlalchemy.sql import select, and_
from ckan import model as model
from ckan.lib.dictization import model_dictize

from ckan.model import User, Package, Session, PackageExtra
from ckanext.kata import settings
import unicodedata


log = logging.getLogger(__name__)

IDA_PID_REGEX = re.compile(r'^urn:nbn:fi:csc-ida.*s$')


def get_unique_package_id():
    '''
    Create new package id by generating a new one. Check that the generated id does not exist already.
    This method should always return a previously unexisting package id. If this method returns None,
    then something is wrong.
    '''

    new_id_exists = True
    i=0
    while new_id_exists and i < 10:
        new_id = unicode(generate_pid())
        existing_id_query = model.Session.query(model.Package)\
                        .filter(model.Package.id == new_id)
        if existing_id_query.first():
            i += 1
            continue
        return new_id
    return None

def generate_pid():
    """
    Generate a permanent Kata identifier
    """
    import datetime
    return "urn:nbn:fi:csc-kata%s" % datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")


def label_list_yso(tag_url):
    """
    Takes tag keyword URL and fetches the labels that link to it.

    :returns: the labels
    """

    _tagspaces = {
        'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        'yso-meta': 'http://www.yso.fi/onto/yso-meta/2007-03-02/',
        'rdfs': "http://www.w3.org/2000/01/rdf-schema#",
        'ysa': "http://www.yso.fi/onto/ysa/",
        'skos': "http://www.w3.org/2004/02/skos/core#",
        'om': "http://www.yso.fi/onto/yso-peilaus/2007-03-02/",
        'dc': "http://purl.org/dc/elements/1.1/",
        'allars': "http://www.yso.fi/onto/allars/",
        'daml': "http://www.daml.org/2001/03/daml+oil#",
        'yso-kehitys': "http://www.yso.fi/onto/yso-kehitys/",
        'owl': "http://www.w3.org/2002/07/owl#",
        'xsd': "http://www.w3.org/2001/XMLSchema#",
        'yso': "http://www.yso.fi/onto/yso/",
    }

    labels = []
    if not tag_url.endswith("?rdf=xml"):
        tag_url += "?rdf=xml" # Small necessary bit.
    request = urllib2.Request(tag_url, headers={"Accept": "application/rdf+xml"})
    try:
        contents = urllib2.urlopen(request).read()
    except (socket.error, urllib2.HTTPError, urllib2.URLError,):
        log.debug("Failed to read tag XML.")
        return []
    try:
        xml = etree.XML(contents)
    except etree.XMLSyntaxError:
        log.debug("Tag XMl syntax error.")
        return []
    for descr in xml.xpath('/rdf:RDF/rdf:Description', namespaces=_tagspaces):
        for tag in ('yso-meta:prefLabel', 'rdfs:label', 'yso-meta:altLabel',):
            nodes = descr.xpath('./%s' % tag, namespaces=_tagspaces)
            for node in nodes:
                text = node.text.strip() if node.text else ''
                if text:
                    labels.append(text)

    for node in xml.xpath('/rdf:RDF/skos:Concept/skos:prefLabel', namespaces=_tagspaces):
        text = node.text.strip() if node.text else None
        if text:
            labels.append(text)

    return labels


def resource_to_dataset(data_dict):
    '''
    Move some fields from resources to dataset. Used for viewing a dataset.

    We need field conversions to make sure the whole 'resources' key in datadict doesn't get overwritten when
    modifying the dataset in WUI. That would drop all manually added resources if resources was already present.

    :param data_dict: the data dictionary
    :returns: the modified data dictionary (resources handled)
    '''
    resource = None

    if 'resources' in data_dict:
        for i in range(len(data_dict['resources'])):
            if data_dict['resources'][i].get('resource_type', None) == settings.RESOURCE_TYPE_DATASET:
                # UI can't handle multiple instances of 'dataset' resources, so now use only the first.
                resource = data_dict['resources'][i]
                break

    if not resource and 'id' in data_dict:
        log.debug('Dataset without a dataset resource: %s', data_dict['id'])
        return data_dict

    if resource:
        data_dict.update({
            'direct_download_URL': resource.get('url', u''),
            'checksum': resource.get('hash', u''),
            'mimetype': resource.get('mimetype', u''),
            'format': resource.get('format', u''),
            'algorithm': resource.get('algorithm', u''),
        })

    return data_dict


def dataset_to_resource(data_dict):
    '''
    Move some fields from dataset to resources. Used for saving to DB.

    Now finds the first 'dataset' resource and updates it. Not sure how this should be handled with multiple
    'dataset' resources. Maybe just remove all of them and add new ones as they all are expected to be present
    when updating a dataset.

    :param data_dict: the data dictionary
    :returns: the modified data dictionary (resources handled)
    '''
    resource_index = None

    if 'resources' in data_dict:
        for i in range(len(data_dict['resources'])):
            if data_dict['resources'][i].get('resource_type', None) == settings.RESOURCE_TYPE_DATASET:
                # Use the first 'dataset' resource.
                resource_index = i
                break

        # SMEAR specific: Remove once this has been run once for smear datasets
        # The goal here is to remove the unnecessary supplements
        for i in range(len(data_dict['resources'])):
            if data_dict['resources'][i].get('resource_type', None) == settings.RESOURCE_TYPE_RDF and \
               data_dict['resources'][i].get('description', None) == 'Current metadata in RDF format' and \
               data_dict['owner_org'] == '15fcc27c-7666-4457-9691-5477f1317713':

                data_dict['resources'][i] = {}
                break
        # END

    else:
        data_dict['resources'] = [None]
        resource_index = 0

    if data_dict.get('availability') != 'direct_download':
        data_dict['direct_download_URL'] = None
        if resource_index is not None:
            # Empty the found 'dataset' resource if availability is not 'direct_download' to get rid of it's URL
            # which is the used as the direct_download_URL.
            data_dict['resources'][resource_index] = {}

    if resource_index is None:
        # Resources present, but no 'dataset' resource found. Add resource to the beginning of list.
        data_dict['resources'].insert(0, {})
        resource_index = 0

    data_dict['resources'][resource_index] = {
        'url': data_dict.get('direct_download_URL', settings.DATASET_URL_UNKNOWN),
        'hash': data_dict.get('checksum', u''),
        'format': data_dict.get('format', u''),
        'mimetype': data_dict.get('mimetype', u''),
        'algorithm': data_dict.get('algorithm', u''),
        'resource_type': settings.RESOURCE_TYPE_DATASET,
    }

    return data_dict


def hide_sensitive_fields(pkg_dict1):
    '''
    Hide fields that contain sensitive data. Modifies input dict directly.

    :param pkg_dict1: data dictionary from package_show
    :returns: the modified data dictionary
    '''

    # pkg_dict1['maintainer_email'] = _('Not authorized to see this information')

    for con in pkg_dict1.get('contact', []):
        # String 'hidden' triggers the link for contact form, see metadata_info.html
        con['email'] = 'hidden'

    return pkg_dict1


def get_field_titles(_):
    '''
    Get correctly translated titles for search fields

    :param _: gettext translator
    :returns: dict of titles for fields
    '''

    translated_field_titles = {}

    for k, v in settings._FIELD_TITLES.iteritems():
        translated_field_titles[k] = _(v)

    return translated_field_titles


def get_field_title(key, _):
    '''
    Get correctly translated title for one search field

    :param _: gettext translator
    :returns: dict of titles for fields
    '''

    return _(settings._FIELD_TITLES[key])


def get_member_role(group_id, user_id):
    """
    Get the user's role for this group.

    :param group_id: Group ID
    :param user_id: User ID
    :rtype: list of strings
    """
    query = model.Session.query(model.Member) \
        .filter(model.Member.group_id == group_id) \
        .filter(model.Member.table_name == 'user') \
        .filter(model.Member.state == 'active') \
        .filter(model.Member.table_id == user_id)

    return fn.first([group.capacity for group in query.all()])


def get_funders(data_dict):
    '''
    Get all funders from agent field in data_dict
    '''
    return filter(lambda x: x.get('role') == u'funder' and
                  (x.get('name') or x.get('id') or x.get('URL') or x.get('organisation')),
                  data_dict.get('agent', []))


def pid_to_name(string):
    '''
    Wrap re.sub to convert a PID to package.name.
    '''
    if string:
        return re.sub(*settings.PID_TO_NAME_REGEXES, string=string)


def get_pids_by_type(pid_type, data_dict, relation=None):
    '''
    Get all package PID dicts of certain type

    :param pid_type: PID type to get (primary, relation)
    :param data_dict:
    :param relation: relation type. None == get all pids. Basically applicable only
            when pid type is relation, otherwise not useful since primary type does
            not have relation defined.
    :rtype: list of dicts
    '''

    return [x for x in data_dict.get('pids', {}) if x.get('type') == pid_type and
            (relation == None or x.get('relation') == relation)]

def get_primary_pid(data_dict, get_as_dict=False):
    '''
    Returns the primary PID of the given type for a package.
    This is a convenience function that returns the first primary PID
    returned by get_pids_by_type.

    If no primary PID can be found, this function returns None.

    :param data_dict:
    :param get_as_dict: If true, return a dictionary, otherwise return plaing string
    :return: the primary identifier of the package
    '''

    pids = get_pids_by_type(pid_type='primary', data_dict=data_dict)
    if pids:
        if get_as_dict:
            return pids[0]
        return pids[0]['id']
    else:
        return None


def get_external_id(data_dict):
    '''
    Returns the external ID.
    External ID is to be used when an external system needs to identify
    this dataset with non-changing ID.

    If no ID can be found, this function returns None.

    :param data_dict:
    :return: the external ID of the package
    :rtype: str or unicode
    '''

    if data_dict.get('external_id'):
        return data_dict.get('external_id')
    return None


def get_package_id_by_pid(pid, pid_type):
    """ Find pid by id and type.

    :param pid: id of the pid
    :param pid_type: type of the pid (primary, relation)
    :return: id of the package
    """
    query = select(['key', 'package_id']).where(and_(model.PackageExtra.value == pid, model.PackageExtra.key.like('pids_%_id'),
                                                     model.PackageExtra.state == 'active'))

    for key, package_id in [('pids_%s_type' % key.split('_')[1], package_id) for key, package_id in Session.execute(query)]:
        query = select(['package_id']).where(and_(model.PackageExtra.value == pid_type, model.PackageExtra.key == key,
                                                  model.PackageExtra.state == 'active', model.PackageExtra.package_id == package_id))
        for package_id, in Session.execute(query):
            return package_id

    return None


def get_package_id_by_primary_pid(data_dict):
    '''
    Try if the provided primary PID matches exactly one dataset.

    THIS METHOD WAS PREVIOUSLY GET_PACKAGE_ID_BY_DATA_PIDS, is the below correct, or should relation pids also be used?

    :param data_dict:
    :return: Package id or None if not found.
    '''
    primary_pid = get_primary_pid(data_dict)
    if not primary_pid:
        return None

    pid_list = [primary_pid]

    # Get package ID's with matching PIDS
    query = Session.query(model.PackageExtra.package_id.distinct()).\
        filter(model.PackageExtra.value.in_(pid_list))
    pkg_ids = query.all()
    if len(pkg_ids) != 1:
        return None              # Nothing to do if we get many or zero datasets

    # Get extras with the received package ID's
    query = select(['key', 'value', 'state']).where(
        and_(model.PackageExtra.package_id.in_(pkg_ids), model.PackageExtra.key.like('pids_%')))

    extras = Session.execute(query)

    # Dictize the results
    extras = model_dictize.extras_list_dictize(extras, {'model': PackageExtra})

    # Check that matching PIDS are type 'primary'.
    for extra in extras:
        key = extra['key'].split('_')   # eg. ['pids', '0', 'id']

        if key[2] == 'id' and extra['value'] in pid_list:
            type_key = '_'.join(key[:2] + ['type'])

            if not filter(lambda x: x['key'] == type_key and (x['value'] == 'primary'), extras):
                return None      # Found a hit with wrong type of PID

    return pkg_ids[0]    # No problems found, so use this


def get_package_contacts(pkg_id):
    """
    Returns contact information for the dataset with the given id.

    :param pkg_id: the id of the package whose contact information to get
    :return: a list of contact information dicts
    :rtype: list of dicts
    """

    contacts_regex = '^(contact)_(\d+)_(.+)$'

    query = select(['id', 'key', 'value', 'state']).where(
        and_(
            model.PackageExtra.package_id == pkg_id,
            model.PackageExtra.key.like('contact_%_%'),
            model.PackageExtra.state == 'active'
        )
    )

    extras = Session.execute(query)
    extras = model_dictize.extras_list_dictize(extras, {'model': PackageExtra})

    contacts_by_index = {}
    for extra in extras:
        key = extra['key']
        value = extra['value']

        match = re.match(contacts_regex, key)
        if match:
            index = match.group(2)
            type = match.group(3)

            contact = contacts_by_index.get(index, {})
            contact[u'index'] = index
            contact[type] = value

            if type == 'email':
                contact[u'id'] = extra['id']

            contacts_by_index[index] = contact

    contacts = [ c for c in contacts_by_index.values() ]
    return sorted(contacts, key=lambda c: int(c['index']))


def is_ida_pid(pid):
    '''
    Determines whether the given string seems to be a PID from the IDA namespace.
    :param pid:
    :return:
    :rtype: bool
    '''

    return pid and IDA_PID_REGEX.match(pid)


def generate_ida_download_url(external_id):
    '''
    Returns an assumed download URL for the data based on the given external ID.

    TODO: this should probably be done at the source end, i.e. in IDA itself or harvesters

    :param external_id: the ID for the IDA dataset
    :return: a download URL for an IDA dataset
    '''

    ida_download_url_template = "https://avaa.tdata.fi/remsida/dl.jsp?pid={p}"
    return ida_download_url_template.format(p=external_id)


def slugify(str):
    '''
    Converts string to a sane url format, e.g. ääöö to aaoo.

    :param str: string to convert
    :return: converted unicode string
    '''

    nkfd_form = unicodedata.normalize('NFKD', str)
    return u"".join([c for c in nkfd_form if not unicodedata.combining(c)])


def remove_trailing_spaces(str):
    if str and isinstance(str, basestring):
        return str.strip()
    return str


def remove_all_spaces(str):
    if str and isinstance(str, basestring):
        return re.sub('\s+', '', str)
    return str