'''
csrf.py

Copyright 2006 Andres Riancho

This file is part of w3af, http://w3af.org/ .

w3af is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation version 2 of the License.

w3af is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with w3af; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

'''
from math import log, floor

import core.controllers.output_manager as om
import core.data.constants.severity as severity

from core.controllers.plugins.audit_plugin import AuditPlugin
from core.controllers.misc.levenshtein import relative_distance_boolean
from core.data.fuzzer.fuzzer import create_mutants
from core.data.fuzzer.mutants.headers_mutant import HeadersMutant
from core.data.kb.vuln import Vuln
from core.data.dc.data_container import DataContainer

COMMON_CSRF_NAMES = [
    'csrf_token',
    'token',
    'csrf'
]


class csrf(AuditPlugin):
    '''
    Identify Cross-Site Request Forgery vulnerabilities.
    
    @author: Taras (oxdef@oxdef.info)
    @author: Andres Riancho (andres.riancho@gmail.com)
    '''

    def __init__(self):
        AuditPlugin.__init__(self)

        self._strict_mode = False
        self._equal_limit = 0.95

    def audit(self, freq, orig_response):
        '''
        Tests a URL for csrf vulnerabilities.

        @param freq: A FuzzableRequest
        '''
        if not self._is_suitable(freq):
            return

        # Referer/Origin check
        #
        # IMPORTANT NOTE: I'm aware that checking for the referer header does
        # NOT protect the application against all cases of CSRF, but it's a
        # very good first step. In order to exploit a CSRF in an application
        # that protects using this method an intruder would have to identify
        # other vulnerabilities such as XSS or open redirects.
        #
        # TODO: This algorithm has lots of room for improvement
        if self._is_origin_checked(freq, orig_response):
            om.out.debug('Origin for %s is checked' % freq.get_url())
            return

        # Does the request have CSRF token in query string or POST payload?
        tokens = self._find_csrf_token(freq)
        if tokens and self._is_token_checked(freq, tokens, orig_response):
            om.out.debug('Token for %s is exist and checked' % freq.get_url())
            return

        # Ok, we have found vulnerable to CSRF attack request
        msg = 'Cross Site Request Forgery has been found at: ' + freq.get_url()
        
        v = Vuln.from_fr('CSRF vulnerability', msg, severity.HIGH,
                         orig_response.id, self.get_name(), freq)
        
        self.kb_append_uniq(self, 'csrf', v)

    def _is_resp_equal(self, res1, res2):
        '''
        @see: unittest for this method in test_csrf.py
        '''
        if res1.get_code() != res2.get_code():
            return False

        if not relative_distance_boolean(res1.body, res2.body, self._equal_limit):
            return False

        return True

    def _is_suitable(self, freq):
        '''
        For CSRF attack we need request with payload and persistent/session
        cookies.

        @return: True if the request can have a CSRF vulnerability
        '''
        for cookie in self._uri_opener.get_cookies():
            if freq.get_url().get_domain() in cookie.domain:
                break
        else:
            return False

        # Strict mode on/off - do we need to audit GET requests? Not always...
        if freq.get_method() == 'GET' and self._strict_mode:
            return False

        # Payload?
        if not freq.get_uri().has_query_string() and not freq.get_dc():
            return False

        om.out.debug('%s is suitable for CSRF attack' % freq.get_url())
        return True

    def _is_origin_checked(self, freq, orig_response):
        '''
        @return: True if the remote web application verifies the Referer before
                 processing the HTTP request.
        '''
        fake_ref = 'http://www.w3af.org/'
        mutant = HeadersMutant(freq.copy())
        mutant.set_var('Referer')
        mutant.set_original_value(freq.get_referer())
        mutant.set_mod_value(fake_ref)
        mutant_response = self._uri_opener.send_mutant(mutant)
        
        if not self._is_resp_equal(orig_response, mutant_response):
            return True
        
        return False

    def _find_csrf_token(self, freq):
        '''
        @return: A dict with the identified token(s) 
        '''
        result = {}
        dc = freq.get_dc()
        
        for param_name in dc:
            for element_index, element_value in enumerate(dc[param_name]):
            
                if self.is_csrf_token(param_name, element_value):
                    
                    if param_name not in result:
                        result[param_name] = {}
                    
                    result[param_name][element_index] = element_value
                    
                    msg = 'Found CSRF token %s in parameter %s for URL %s.'
                    om.out.debug(msg % (element_value,
                                        param_name,
                                        freq.get_url()))
                    
                    break
        
        return result

    def _is_token_checked(self, freq, token, orig_response):
        om.out.debug('Testing for validation of token in %s' % freq.get_url())
        mutants = create_mutants(freq, ['123'], False, token.keys())
        for mutant in mutants:
            mutant_response = self._uri_opener.send_mutant(mutant, analyze=False)
            if not self._is_resp_equal(orig_response, mutant_response):
                return True
        return False

    def is_csrf_token(self, key, value):
        # Entropy based algoritm
        # http://en.wikipedia.org/wiki/Password_strength
        min_length = 4
        min_entropy = 36
        
        # Check for common CSRF token names
        if key in COMMON_CSRF_NAMES and value:
            return True
        
        # Check length
        if len(value) < min_length:
            return False
        
        # Calculate entropy
        total = 0
        total_digit = False
        total_lower = False
        total_upper = False
        total_spaces = False

        for i in value:
            if i.isdigit():
                total_digit = True
                continue
            if i.islower():
                total_lower = True
                continue
            if i.isupper():
                total_upper = True
                continue
            if i == ' ':
                total_spaces = True
                continue
        total = int(
            total_digit) * 10 + int(total_upper) * 26 + int(total_lower) * 26
        entropy = floor(log(total) * (len(value) / log(2)))
        if entropy >= min_entropy:
            if not total_spaces and total_digit:
                return True
        return False

    def get_long_desc(self):
        '''
        @return: A DETAILED description of the plugin functions and features.
        '''
        return '''
        This plugin finds Cross Site Request Forgeries (csrf) vulnerabilities.

        The simplest type of csrf is checked to be vulnerable, the web application
        must have sent a permanent cookie, and the aplicacion must have query
        string parameters.
        '''
