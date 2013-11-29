# coding: utf-8
#
# pylint: disable=no-self-use, missing-docstring, too-many-public-methods, invalid-name

"""
Test classes for Kata CKAN Extension.
"""

import copy
from unittest import TestCase
from collections import defaultdict

from pylons.util import PylonsContext, pylons, AttribSafeContextObj
from pylons import config, test
import paste.fixture  # pylint: disable=import-error

from ckanext.kata.settings import get_field_titles, _FIELD_TITLES, get_field_title
from ckanext.kata.plugin import KataPlugin
from ckan.tests import WsgiAppCase, CommonFixtureMethods, call_action_api
from ckan.tests.html_check import HtmlCheckMethods
from ckan.config.middleware import make_app
from ckanext.kata.validators import validate_kata_date, check_project, \
    check_project_dis, validate_email, validate_phonenum, \
    validate_discipline, validate_spatial, validate_algorithm, \
    validate_mimetype, validate_general
from ckan.lib.navl.dictization_functions import Invalid, flatten_dict
from ckanext.kata.converters import remove_disabled_languages, checkbox_to_boolean, convert_languages
from ckanext.kata import settings, utils, actions, converters, model as kata_model
from ckan.lib.create_test_data import CreateTestData
from ckan import model


class TestKataExtension(TestCase):
    """General tests for Kata CKAN extension."""

    def test_get_field_titles(self):
        """Test settings.get_field_titles()"""

        titles = get_field_titles(lambda x: x)

        assert len(titles) > 2, 'Found less than 3 field titles'
        assert 'tags' in titles, 'No tags field found in field titles'
        assert 'authorstring' in titles, 'No authorstring field found in field titles'

    def test_get_field_titles_translate(self):
        """Test settings.get_field_titles() translation"""

        translator = lambda x: x[::-1]  # Reverse string

        titles = get_field_titles(translator)

        assert translator(_FIELD_TITLES['tags']) in titles.values(), 'No tags field found in field titles'
        assert translator(_FIELD_TITLES['authorstring']) in titles.values(), 'No authorstring found in field titles'

    def test_get_field_title(self):
        """Test settings.get_field_title()"""

        translator = lambda x: x[::-1]  # Reverse string

        title = get_field_title('tags', translator)

        assert translator(_FIELD_TITLES['tags']) == title


class TestKataPlugin(WsgiAppCase, HtmlCheckMethods, CommonFixtureMethods):
    """
    General tests for KataPlugin.

    Provides a a dummy context object to test functions and methods that rely on it.
    """

    @classmethod
    def setup_class(cls):
        """Set up tests."""

        wsgiapp = make_app(config['global_conf'], **config['app_conf'])
        cls.app = paste.fixture.TestApp(wsgiapp)

        cls.some_data_dict = {'sort': u'metadata_modified desc',
                              'fq': '',
                              'rows': 20,
                              'facet.field': ['groups',
                                              'tags',
                                              'extras_fformat',
                                              'license',
                                              'authorstring',
                                              'organizationstring',
                                              'extras_language'],
                              'q': u'',
                              'start': 0,
                              'extras': {'ext_author-4': u'testauthor',
                                         'ext_date-metadata_modified-end': u'2013',
                                         'ext_date-metadata_modified-start': u'2000',
                                         'ext_groups-6': u'testdiscipline',
                                         'ext_operator-2': u'OR',
                                         'ext_operator-3': u'AND',
                                         'ext_operator-4': u'AND',
                                         'ext_operator-5': u'OR',
                                         'ext_operator-6': u'NOT',
                                         'ext_organization-3': u'testorg',
                                         'ext_tags-1': u'testkeywd',
                                         'ext_tags-2': u'testkeywd2',
                                         'ext_title-5': u'testtitle'}
        }
        cls.short_data_dict = {'sort': u'metadata_modified desc',
                               'fq': '',
                               'rows': 20,
                               'facet.field': ['groups',
                                               'tags',
                                               'extras_fformat',
                                               'license',
                                               'authorstring',
                                               'organizationstring',
                                               'extras_language'],
                               'q': u'',
                               'start': 0,
        }
        cls.test_q_terms = u' ((tags:testkeywd) OR ( tags:testkeywd2 AND ' + \
                           u'organization:testorg AND author:testauthor) OR ' + \
                           u'( title:testtitle NOT groups:testdiscipline))'
        cls.test_q_dates = u' metadata_modified:[2000-01-01T00:00:00.000Z TO ' + \
                           u'2013-12-31T23:59:59.999Z]'
        cls.kata_plugin = KataPlugin()

        # The Pylons globals are not available outside a request. This is a hack to provide context object.
        c = AttribSafeContextObj()
        py_obj = PylonsContext()
        py_obj.tmpl_context = c
        pylons.tmpl_context._push_object(c)

    @classmethod
    def teardown_class(cls):
        """Get away from testing environment."""

        pylons.tmpl_context._pop_object()

    def test_extract_search_params(self):
        """Test extract_search_params() output parameters number."""
        terms, ops, dates = self.kata_plugin.extract_search_params(self.some_data_dict)
        n_extracted = len(terms) + len(ops) + len(dates)
        assert len(self.some_data_dict['extras']) == n_extracted - 1, \
            "KataPlugin.extract_search_params() parameter number mismatch"
        assert len(terms) == len(ops) + 1, \
            "KataPlugin.extract_search_params() term/operator ratio mismatch"

    def test_parse_search_terms(self):
        """Test parse_search_terms() result string."""
        test_dict = self.some_data_dict.copy()
        terms, ops, dates = self.kata_plugin.extract_search_params(self.some_data_dict)
        self.kata_plugin.parse_search_terms(test_dict, terms, ops)
        assert test_dict['q'] == self.test_q_terms, \
            "KataPlugin.parse_search_terms() error in query parsing q=%s, test_q_terms=%s" % (
                test_dict['q'], self.test_q_terms)

    def test_parse_search_dates(self):
        """Test parse_search_dates() result string."""
        test_dict = self.some_data_dict.copy()
        terms, ops, dates = self.kata_plugin.extract_search_params(self.some_data_dict)
        self.kata_plugin.parse_search_dates(test_dict, dates)
        assert test_dict['q'] == self.test_q_dates, \
            "KataPlugin.parse_search_dates() error in query parsing"

    def test_before_search(self):
        """Test before_search() output type and more."""
        result_dict = self.kata_plugin.before_search(self.some_data_dict.copy())
        assert isinstance(result_dict, dict), "KataPlugin.before_search() didn't output a dict"

        # Test that no errors occur without 'extras'
        self.kata_plugin.before_search(self.short_data_dict)

    def test_get_actions(self):
        """Test get_actions() output type."""
        assert isinstance(self.kata_plugin.get_actions(), dict), "KataPlugin.get_actions() didn't output a dict"

    def test_get_helpers(self):
        """Test get_helpers() output type."""
        assert isinstance(self.kata_plugin.get_helpers(), dict), "KataPlugin.get_helpers() didn't output a dict"


    def test_new_template(self):
        html_location = self.kata_plugin.new_template()
        assert len(html_location) > 0

    def test_comments_template(self):
        html_location = self.kata_plugin.comments_template()
        assert len(html_location) > 0

    def test_search_template(self):
        html_location = self.kata_plugin.search_template()
        assert len(html_location) > 0

    def test_read_template(self):
        html_location = self.kata_plugin.read_template()
        assert len(html_location) > 0

    def test_history_template(self):
        html_location = self.kata_plugin.history_template()
        assert len(html_location) > 0

    def test_package_form(self):
        html_location = self.kata_plugin.package_form()
        assert len(html_location) > 0


    def test_create_package_schema(self):
        schema = self.kata_plugin.create_package_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0

    def test_update_package_schema(self):
        schema = self.kata_plugin.update_package_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0

    def test_show_package_schema(self):
        schema = self.kata_plugin.show_package_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0


class TestKataValidators(TestCase):
    """Tests for Kata validators."""

    @classmethod
    def setup_class(cls):
        """Set up tests."""

        # TODO: Get a new flattened data_dict

        cls.test_data = {('__extras',): {'_ckan_phase': u'',
                'evdescr': [],
                'evwhen': [],
                'evwho': [],
                'groups': [],
                'pkg_name': u''},
            ('availability',): u'contact',
            ('access_application_URL',): u'',
            ('access_request_URL',): u'',
            ('algorithm',): u'',
            ('author', 0, 'value'): u'dada',
            ('checksum',): u'',
            ('contact_URL',): u'http://google.com',
            ('discipline',): u'',
            ('evtype', 0, 'value'): u'collection',
            ('extras',): [{'key': 'funder', 'value': u''},
                {'key': 'discipline', 'value': u''},
                {'key': 'maintainer', 'value': u'dada'},
                {'key': 'mimetype', 'value': u''},
                {'key': 'project_funding', 'value': u''},
                {'key': 'project_homepage', 'value': u''},
                {'key': 'owner', 'value': u'dada'},
                {'key': 'temporal_coverage_begin', 'value': u''},
                {'key': 'direct_download_URL', 'value': u''},
                {'key': 'phone', 'value': u'+35805050505'},
                {'key': 'license_URL', 'value': u'dada'},
                {'key': 'geographic_coverage', 'value': u''},
                {'key': 'access', 'value': u'contact'},
                {'key': 'algorithm', 'value': u''},
                {'key': 'langdis', 'value': u'True'},
                {'key': 'access_application_URL', 'value': u''},
                {'key': 'contact_URL', 'value': u'http://google.com'},
                {'key': 'project_name', 'value': u''},
                {'key': 'checksum', 'value': u''},
                {'key': 'temporal_coverage_end', 'value': u''},
                {'key': 'projdis', 'value': u'True'},
                {'key': 'language', 'value': u''}],
            ('mimetype',): u'',
            ('project_funder',): u'',
            ('geographic_coverage',): u'',
            ('langdis',): u'False',
            ('language',): u'swe',
            ('license_URL',): u'dada',
            ('license_id',): u'',
            ('log_message',): u'',
            ('name',): u'',
            ('notes',): u'',
            ('organization', 0, 'value'): u'dada',
            ('owner',): u'dada',
            ('phone',): u'+35805050505',
            ('maintainer_email',): u'kata.selenium@gmail.com',
            ('projdis',): u'True',
            ('project_funding',): u'',
            ('project_homepage',): u'',
            ('project_name',): u'',
            ('maintainer',): u'dada',
            ('save',): u'finish',
            ('tag_string',): u'dada',
            ('temporal_coverage_begin',): u'',
            ('temporal_coverage_end',): u'',
            ('title', 0, 'lang'): u'sv',
            ('title', 0, 'value'): u'dada',
            ('type',): None,
            ('version',): u'2013-08-14T10:37:09Z',
            ('version_PID',): u''}

    def test_validate_kata_date_valid(self):
        errors = defaultdict(list)
        validate_kata_date('date', {'date': '2012-12-31T13:12:11'}, errors, None)
        assert len(errors) == 0

    def test_validate_kata_date_invalid(self):
        errors = defaultdict(list)
        validate_kata_date('date', {'date': '20xx-xx-31T13:12:11'}, errors, None)
        assert len(errors) > 0

    def test_validate_kata_date_invalid_2(self):
        errors = defaultdict(list)
        validate_kata_date('date', {'date': '2013-02-29T13:12:11'}, errors, None)
        assert len(errors) > 0


    def test_validate_language_valid(self):
        errors = defaultdict(list)
        convert_languages(('language',), self.test_data, errors, None)
        assert len(errors) == 0

    def test_remove_disabled_languages_valid(self):
        errors = defaultdict(list)
        remove_disabled_languages(('language',), self.test_data, errors, None)
        assert len(errors) == 0

    def test_validate_language_valid_2(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('language',)] = u''
        dada[('langdis',)] = 'True'

        convert_languages(('language',), dada, errors, None)
        assert len(errors) == 0

        remove_disabled_languages(('language',), dada, errors, None)
        assert len(errors) == 0

    def test_validate_language_valid_3(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('language',)] = u'fin, swe, eng, isl'
        dada[('langdis',)] = 'False'

        convert_languages(('language',), dada, errors, None)
        assert len(errors) == 0

        remove_disabled_languages(('language',), dada, errors, None)
        assert len(errors) == 0
        assert dada[('language',)] == u'fin, swe, eng, isl'

    def test_validate_language_delete(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('language',)] = u'fin, swe, eng, ita'
        dada[('langdis',)] = 'True'

        convert_languages(('language',), dada, errors, None)
        assert len(errors) == 0

        remove_disabled_languages(('language',), dada, errors, None)
        assert len(errors) == 0
        assert dada[('language',)] == u''

    def test_validate_language_invalid(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('language',)] = u'aa, ab, ac, ad, ae, af'
        dada[('langdis',)] = 'False'

        convert_languages(('language',), dada, errors, None)
        assert len(errors) == 1

    def test_validate_language_invalid_2(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('language',)] = u''
        dada[('langdis',)] = 'False'

        convert_languages(('language',), dada, errors, None)
        remove_disabled_languages(('language',), dada, errors, None)
        assert len(errors) == 1

    def test_validate_language_invalid_3(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('language',)] = u'finglish, sv, en'
        dada[('langdis',)] = 'True'

        convert_languages(('language',), dada, errors, None)
        assert len(errors) == 1

    def test_project_valid(self):
        errors = defaultdict(list)
        dada = copy.deepcopy(self.test_data)
        dada[('projdis',)] = 'False'
        dada[('funder',)] = u'funder'
        dada[('project_name',)] = u'project name'
        dada[('project_funding',)] = u'project_funding'
        dada[('project_homepage',)] = u'www.google.fi'

        check_project_dis(('project_name',),
                          dada, errors, None)
        assert len(errors) == 0
        check_project_dis(('funder',),
                          dada, errors, None)
        assert len(errors) == 0
        check_project_dis(('project_funding',),
                          dada, errors, None)
        assert len(errors) == 0
        check_project_dis(('project_homepage',),
                          dada, errors, None)
        assert len(errors) == 0

    def test_project_invalid(self):
        errors = defaultdict(list)
        dada = copy.deepcopy(self.test_data)
        dada[('projdis',)] = 'False'
        dada[('funder',)] = u''
        dada[('project_name',)] = u'project name'
        dada[('project_funding',)] = u'project_funding'
        dada[('project_homepage',)] = u'www.google.fi'

        check_project_dis(('project_name',),
                          dada, errors, None)
        assert len(errors) == 0
        check_project_dis(('funder',),
                          dada, errors, None)
        assert len(errors) > 0

    def test_project_notgiven(self):
        errors = defaultdict(list)
        dada = copy.deepcopy(self.test_data)
        dada[('projdis',)] = 'True'
        dada[('project_name',)] = u'project name'
        check_project(('project_name',),
                      dada, errors, None)
        print errors
        assert len(errors) > 0

    def test_validate_email_valid(self):
        errors = defaultdict(list)

        validate_email(('maintainer_email',), self.test_data, errors, None)

        assert len(errors) == 0

    def test_validate_email_valid_2(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('maintainer_email',)] = u'a.b.c.d@e.com'

        validate_email(('maintainer_email',), dada, errors, None)

        assert len(errors) == 0

    def test_validate_email_invalid(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('maintainer_email',)] = u'a.b.c.d'

        validate_email(('maintainer_email',), dada, errors, None)

        assert len(errors) == 1

    def test_validate_email_invalid_2(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('maintainer_email',)] = u'a.b@com'

        validate_email(('maintainer_email',), dada, errors, None)

        assert len(errors) == 1

    def test_validate_phonenum_valid(self):
        errors = defaultdict(list)

        validate_phonenum(('phone',), self.test_data, errors, None)

        assert len(errors) == 0

    def test_validate_phonenum_invalid(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('phone',)] = u'123_notgood_456'

        validate_phonenum(('phone',), dada, errors, None)

        assert len(errors) == 1
        
    def test_general_validator_invalid(self):
        errors = defaultdict(list)
        
        dada = copy.deepcopy(self.test_data)
        dada[('project_homepage',)] = u'http://www.<asdf123456>'
        
        validate_general(('project_homepage',), dada, errors, None)
        assert len(errors) == 1

    def test_validate_discipline(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('discipline',)] = u'Matematiikka'

        validate_discipline(('discipline',), dada, errors, None)
        assert len(errors) == 0

        del dada[('discipline',)]
        validate_discipline(('discipline',), dada, errors, None)
        assert len(errors) == 0

        dada[('discipline',)] = u'Matematiikka (Logiikka!)'
        self.assertRaises(Invalid, validate_discipline, ('discipline',), dada, errors, None)

    def test_validate_spatial(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('geographic_coverage',)] = u'Uusimaa (laani)'

        validate_spatial(('geographic_coverage',), dada, errors, None)
        assert len(errors) == 0

        del dada[('geographic_coverage',)]
        validate_spatial(('geographic_coverage',), dada, errors, None)
        assert len(errors) == 0

        dada[('geographic_coverage',)] = u'Uusimaa ([]!)'
        self.assertRaises(Invalid, validate_spatial, ('geographic_coverage',), dada, errors, None)

    def test_checkbox_to_boolean(self):
        errors = defaultdict(list)

        dada = copy.deepcopy(self.test_data)
        dada[('langdis',)] = u'True'
        checkbox_to_boolean(('langdis',), dada, errors, None)
        assert dada[('langdis',)] == u'True'

        dada[('langdis',)] = u'False'
        checkbox_to_boolean(('langdis',), dada, errors, None)
        assert dada[('langdis',)] == u'False'

        dada[('langdis',)] = u'on'
        checkbox_to_boolean(('langdis',), dada, errors, None)
        assert dada[('langdis',)] == u'True'

        dada[('langdis',)] = u''
        checkbox_to_boolean(('langdis',), dada, errors, None)
        assert dada[('langdis',)] == u'False'


class TestResouceConverters(TestCase):
    """Unit tests for resource conversions related to actions."""

    @classmethod
    def setup_class(cls):
        """Set up tests."""

        cls.test_data = {
            'id': u'test',
            'direct_download_URL': u'http://www.csc.fi',
            'algorithm': u'MD5',
            'checksum': u'f60e586509d99944e2d62f31979a802f',
            'mimetype': u'application/pdf',
        }

        cls.test_data2 = {
            'id': u'test',
            'resources': [{
                'url': u'http://www.csc.fi',
                'algorithm': u'MD5',
                'hash': u'f60e586509d99944e2d62f31979a802f',
                'mimetype': u'application/pdf',
                'resource_type': settings.RESOURCE_TYPE_DATASET,
            }]}

        cls.test_data3 = {
            'id': u'test',
            'resources': [{
                'url': u'http://www.csc.fi',
                'algorithm': u'MD5',
                'hash': u'f60e586509d99944e2d62f31979a802f',
                'mimetype': u'application/pdf',
                'resource_type': settings.RESOURCE_TYPE_DATASET,
            },
            {
                'url': u'http://www.helsinki.fi',
                'algorithm': u'SHA',
                'hash': u'somehash',
                'mimetype': u'application/csv',
                'resource_type': 'file',
            }]}

    def test_dataset_to_resource(self):
        data_dict = copy.deepcopy(self.test_data)
        assert 'resources' not in data_dict

        converters.to_resource('direct_download_URL', data_dict, [], {})
        assert 'resources' in data_dict

        converters.to_resource('direct_download_URL', data_dict, [], {})
        assert 'resources' in data_dict

    def test_dataset_to_resource_invalid(self):
        data_dict = copy.deepcopy(self.test_data)
        data_dict.pop('direct_download_URL')
        data_dict.pop('checksum')
        data_dict.pop('mimetype')
        assert 'resources' not in data_dict

        converters.to_resource('direct_download_URL', data_dict, [], {})
        # dataset_to_resource can handle missing data, so resources is created
        assert 'resources' in data_dict

    def test_resource_to_dataset(self):
        data_dict = copy.deepcopy(self.test_data2)
        converters.from_resource('key', data_dict, [], {})
        assert 'direct_download_URL' in data_dict

    def test_resource_to_dataset_invalid(self):
        data_dict = copy.deepcopy(self.test_data2)
        data_dict['resources'][0].pop('resource_type')
        converters.from_resource('key', data_dict, [], {})
        assert 'direct_download_URL' not in data_dict

    def test_resource_juggling(self):
        data_dict = copy.deepcopy(self.test_data3)

        converters.from_resource('key', data_dict, [], {})
        converters.to_resource('direct_download_URL', data_dict, [], {})
        converters.from_resource('key', data_dict, [], {})
        converters.to_resource('direct_download_URL', data_dict, [], {})
        converters.from_resource('key', data_dict, [], {})

        assert len(data_dict['resources']) == 1
        assert 'direct_download_URL' in data_dict
        assert data_dict['direct_download_URL'] == self.test_data2['resources'][0]['url']

        # Add a new dataset resource manually
        data_dict['resources'].append(copy.deepcopy(self.test_data2['resources'][0]))

        print len(data_dict['resources'])
        converters.to_resource('direct_download_URL', data_dict, [], {})
        converters.from_resource('key', data_dict, [], {})
        converters.to_resource('direct_download_URL', data_dict, [], {})
        converters.from_resource('key', data_dict, [], {})
        print len(data_dict['resources'])

        assert len(data_dict['resources']) == 2
        assert 'direct_download_URL' in data_dict
        assert data_dict['direct_download_URL'] == self.test_data2['resources'][0]['url']


class TestResourceValidators(TestCase):
    '''
    Test validators for resources
    '''
    
    @classmethod
    def setup_class(cls):
        '''
        Using the resource's format for resource validator tests
        '''
        cls.test_data = {
            'resources': [{
                'url' : u'http://www.csc.fi',
                'algorithm': u'MD5',
                'hash': u'f60e586509d99944e2d62f31979a802f',
                'mimetype': u'application/pdf',
                'resource_type' : settings.RESOURCE_TYPE_DATASET,
                }]
            }
    
    def test_validate_mimetype_valid(self):
        errors = defaultdict(list)
        
        data_dict = copy.deepcopy(self.test_data)
        data_dict['resources'][0]['mimetype'] = u'vnd.3gpp2.bcmcsinfo+xml/'
        # flatten dict (or change test_data to flattened form?)
        data = flatten_dict(data_dict)
        try:
            validate_mimetype(('resources', 0, 'mimetype',), data, errors, None)
        except Invalid:
            raise AssertionError('Mimetype raised exception, it should not')
    
    def test_validate_mimetype_invalid(self):
        errors = defaultdict(list)
        
        data_dict = copy.deepcopy(self.test_data)
        data_dict['resources'][0]['mimetype'] = u'application/pdf><'
        data = flatten_dict(data_dict)
        
        self.assertRaises(Invalid, validate_mimetype, ('resources', 0, 'mimetype',), data, errors, None)

    def test_validate_algorithm_valid(self):
        errors = defaultdict(list)
        
        data_dict = copy.deepcopy(self.test_data)
        data_dict['resources'][0]['algorithm'] = u'RadioGatún-1216'
        data = flatten_dict(data_dict)
        
        try:
            validate_algorithm(('resources', 0, 'algorithm',), data, errors, None)
        except Invalid:
            raise AssertionError('Algorithm raised exception, it should not')
        
    def test_validate_algorithm_invalid(self):
        errors = defaultdict(list)
        
        data_dict = copy.deepcopy(self.test_data)
        data_dict['resources'][0]['algorithm'] = u'RadioGatún-1216!>'
        data = flatten_dict(data_dict)
        
        self.assertRaises(Invalid, validate_algorithm, ('resources', 0, 'algorithm',), data, errors, None)


class TestUtils(TestCase):
    """Unit tests for other functions in utils.py."""

    @classmethod
    def setup_class(cls):
        """Set up tests."""
        pass

    def test_generate_pid(self):
        pid = utils.generate_pid()
        assert 'urn' in pid
        assert len(pid) >= 10

    def test_generate_pid2(self):
        pid = utils.generate_pid()
        pid2 = utils.generate_pid()
        assert pid != pid2


class TestActions(TestCase):
    """Unit tests for action functions."""

    @classmethod
    def setup_class(cls):
        """Set up tests."""
        pass

    def test_group_list(self):
        group_list = actions.group_list({}, {})
        assert isinstance(group_list, dict)


class TestCreateDataset(TestCase):
    """Tests for adding a dataset and related functionalities."""

    @classmethod
    def setup_class(cls):
        """Set up tests."""

        kata_model.setup()
        CreateTestData.create()
        cls.sysadmin_user = model.User.get('testsysadmin')

        wsgiapp = make_app(config['global_conf'], **config['app_conf'])
        cls.app = paste.fixture.TestApp(wsgiapp)

        cls.some_resource = {'url': u'http://www.helsinki.fi',
                             'algorithm': u'SHA',
                             'hash': u'somehash',
                             'mimetype': u'application/csv',
                             'resource_type': 'file'}

        cls.test_data = {'access_application_URL': u'',
                         'access_request_URL': u'',
                         'algorithm': u'MD5',
                         'availability': u'direct_download',
                         'checksum': u'f60e586509d99944e2d62f31979a802f',
                         'contact_URL': u'http://www.helsinki.fi/jaskan_kotisivu/',
                         'contact_phone': u'05549583',
                         'direct_download_URL': u'http://helsinki.fi/data-on-taalla',
                         'discipline': u'Tietojenkäsittely ja informaatiotieteet',
                         'evdescr': [{'value': u'Keräsin dataa'},
                                     {'value': u'Julkaistu vihdoinkin'},
                                     {'value': u'hajotti kaiken'}],
                         'evtype': [{'value': u'creation'},
                                    {'value': u'published'},
                                    {'value': u'modified'}],
                         'evwhen': [{'value': u'2000-01-01'},
                                    {'value': u'2010-04-15'},
                                    {'value': u'2013-11-18'}],
                         'evwho': [{'value': u'Tekijä Aineiston'},
                                   {'value': u'Julkaisija Aineiston'},
                                   {'value': u'T. Uhoaja'}],
                         'geographic_coverage': u'Keilaniemi (populated place),Espoo (city)',
                         'langdis': 'False',
                         'langtitle': [{'lang': u'fin', 'value': u'Main Title'},
                                       {'lang': u'abk', 'value': u'Title 2'},
                                       {'lang': u'swe', 'value': u'Title 3'}],
                         'language': u'eng, fin, swe',
                         'license_id': u'notspecified',
                         'maintainer': u'Jaakko Jakelija',
                         'maintainer_email': u'jaakko.jakelija@hy.fi',
                         'mimetype': u'application/csv',
                         'name': u'',
                         'notes': u'Vapaamuotoinen kuvaus aineistosta.',
                         'orgauth': [{'org': u'CSC Oy', 'value': u'Tekijä Aineiston (DC:Creator)'},
                                     {'org': u'Helsingin Yliopisto', 'value': u'Timo Tutkija'},
                                     {'org': u'Kolmas Oy', 'value': u'Kimmo Kolmas'}],
                         'owner': u'Omistaja Aineiston',
                         'pkg_name': u'',
                         'projdis': 'False',
                         'project_funder': u'NSA',
                         'project_funding': u'1234-rahoituspäätösnumero',
                         'project_homepage': u'http://www.nsa.gov',
                         'project_name': u'Data Jakoon -projekti',
                         'tag_string': u'Python,ohjelmoitunut solukuolema,programming',
                         'temporal_coverage_begin': u'2003-07-10T06:36:27Z',
                         'temporal_coverage_end': u'2010-04-15T03:24:47Z',
                         'title': u'',
                         'type': 'dataset',
                         'version': u'2013-11-18T12:25:53Z',
                         'version_PID': u'aineiston-version-pid'}

    def test_create_dataset(self):
        output = call_action_api(self.app, 'package_create', apikey=self.sysadmin_user.apikey,
                                status=200, **self.test_data)
        if '__type' in output:
            assert output['__type'] != 'Validation Error'
        assert output

    def test_create_dataset_and_resources(self):
        '''
        Add a dataset and 2 resources through API
        '''
        print 'Create dataset'
        output = call_action_api(self.app, 'package_create', apikey=self.sysadmin_user.apikey,
                                 status=200, **self.test_data)
        if '__type' in output:
            assert output['__type'] != 'Validation Error'
        assert 'id' in output

        print 'Add resource #1'
        new_res = copy.deepcopy(self.some_resource)
        new_res['package_id'] = output['id']

        output = call_action_api(self.app, 'resource_create', apikey=self.sysadmin_user.apikey,
                                 status=200, **new_res)
        if '__type' in output:
            assert output['__type'] != 'Validation Error'
        assert output

        print 'Add resource #2'
        output = call_action_api(self.app, 'resource_create', apikey=self.sysadmin_user.apikey,
                                 status=200, **new_res)
        if '__type' in output:
            assert output['__type'] != 'Validation Error'
        assert output

    def test_create_update_delete_dataset(self):
        '''
        Add, modify and delete a dataset through API
        '''
        print 'Create dataset'
        output = call_action_api(self.app, 'package_create', apikey=self.sysadmin_user.apikey,
                                 status=200, **self.test_data)
        if '__type' in output:
            assert output['__type'] != 'Validation Error'
        assert 'id' in output

        data_dict = copy.deepcopy(self.test_data)
        data_dict['id'] = output['id']

        print 'Update dataset'
        output = call_action_api(self.app, 'package_update', apikey=self.sysadmin_user.apikey,
                                 status=200, **data_dict)
        if '__type' in output:
            assert output['__type'] != 'Validation Error'
        assert output

        print 'Update dataset'
        output = call_action_api(self.app, 'package_update', apikey=self.sysadmin_user.apikey,
                                 status=200, **data_dict)
        if '__type' in output:
            assert output['__type'] != 'Validation Error'
        assert output

        print 'Delete dataset'
        output = call_action_api(self.app, 'package_delete', apikey=self.sysadmin_user.apikey,
                                 status=200, id=data_dict['id'])

    def test_create_dataset_fails(self):
        data = copy.deepcopy(self.test_data)

        # Make sure we will get a validation error
        data.pop('langtitle')
        data.pop('language')
        data['projdis'] = u'True'

        output = call_action_api(self.app, 'package_create', apikey=self.sysadmin_user.apikey,
                                status=409, **data)

        assert '__type' in output
        assert output['__type'] == 'Validation Error'
        assert 'projdis' in output

