import time
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.core import mail
from accounts.models import Role
from .models import CustomerGoogleIdentity, RegistrationSource
from .services import create_customer_with_user
from .authentication import CustomerPasswordResetForm

User=get_user_model()

class ReleaseAuthTests(TestCase):
    def test_password_rules_and_registration_auto_login(self):
        url=reverse('customers:customer_register')
        self.assertContains(self.client.get(url),'password-rules')
        r=self.client.post(url,{'first_name':'Mira','username':'mira','email':'mira@example.com','password':'Strong-fixture-57!','confirm_password':'Strong-fixture-57!','accept_terms':'on','next':'https://evil.example/'})
        self.assertRedirects(r,'/',fetch_redirect_response=False)
        user=User.objects.get(username='mira')
        self.assertEqual(str(user.pk),self.client.session['_auth_user_id'])
        self.assertIsNone(user.phone_number)
        self.assertFalse(user.is_staff)

    def test_login_defaults_home_and_preserves_checkout(self):
        create_customer_with_user(user_data={'username':'mira','email':'mira@example.com','password':'Strong-fixture-57!'},registration_source=RegistrationSource.WEBSITE)
        for target, expected in [('', '/'),('/checkout/','/checkout/'),('//evil.example/','/')]:
            self.client.logout()
            r=self.client.post(reverse('customers:customer_portal_login'),{'username':'mira','password':'Strong-fixture-57!','next':target})
            self.assertEqual(r.url,expected)

    @override_settings(CUSTOMER_EMAIL_ENABLED=True,EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_reset_is_customer_only_and_token_single_use(self):
        _,u=create_customer_with_user(user_data={'username':'mira','email':'mira@example.com','password':'Strong-fixture-57!'},registration_source=RegistrationSource.WEBSITE)
        admin=User.objects.create_user(username='staff',email='staff@example.com',password='Strong-fixture-57!',role=Role.ADMIN,is_staff=True)
        self.assertEqual(list(CustomerPasswordResetForm().get_users(admin.email)),[])
        for email in ['mira@example.com','staff@example.com','missing@example.com']:
            r=self.client.post(reverse('customers:password_reset'),{'email':email})
            self.assertEqual(r.status_code,302)
        self.assertEqual(len(mail.outbox),1)
        self.assertNotIn('staff@example.com',mail.outbox[0].to)
        token=default_token_generator.make_token(u)
        reset=reverse('customers:password_reset_confirm',args=[urlsafe_base64_encode(force_bytes(u.pk)),token])
        r=self.client.get(reset)
        self.assertEqual(r.status_code,302)
        r=self.client.post(r.url,{'new_password1':'Changed-fixture-89!','new_password2':'Changed-fixture-89!'})
        self.assertEqual(r.status_code,302)
        u.refresh_from_db();self.assertFalse(default_token_generator.check_token(u,token))

    @override_settings(GOOGLE_OAUTH_CLIENT_ID='test-client',GOOGLE_OAUTH_CLIENT_SECRET='test-secret')
    @patch('customers.authentication.verified_google_claims')
    def test_google_creates_customer_and_does_not_link_existing_email(self,verify):
        verify.return_value={'sub':'google-subject','email':'mira@example.com','given_name':'Mira'}
        start=reverse('customers:google_start');callback=reverse('customers:google_callback')
        self.assertEqual(self.client.get(start).status_code,405)
        self.client.post(start,{'accept_terms':'on'})
        state=self.client.session['google_login']['state']
        r=self.client.get(callback,{'state':state,'code':'fixture'})
        self.assertEqual(r.url,'/')
        identity=CustomerGoogleIdentity.objects.get(subject='google-subject')
        self.assertEqual(identity.user.role,Role.CUSTOMER)
        self.assertFalse(identity.user.has_usable_password())
        self.client.logout();verify.return_value['sub']='another-subject'
        self.client.post(start,{'accept_terms':'on'});state=self.client.session['google_login']['state']
        self.client.get(callback,{'state':state,'code':'fixture'})
        self.assertEqual(CustomerGoogleIdentity.objects.count(),1)
        self.assertNotIn('_auth_user_id',self.client.session)

    @override_settings(GOOGLE_OAUTH_CLIENT_ID='test-client',GOOGLE_OAUTH_CLIENT_SECRET='test-secret')
    @patch('customers.authentication.verified_google_claims')
    def test_google_rejects_state_replay_and_requires_csrf(self,verify):
        c=Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(reverse('customers:google_start'),{'accept_terms':'on'}).status_code,403)
        self.client.post(reverse('customers:google_start'),{'accept_terms':'on'})
        self.client.get(reverse('customers:google_callback'),{'state':'incorrect','code':'fixture'})
        self.assertFalse(verify.called)
        self.assertNotIn('google_login',self.client.session)
