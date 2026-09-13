import uuid
from django import forms
from django.core import signing
from .import_contract import MAX_CSV_BYTES
from .import_permissions import available_stores


class ImportUploadForm(forms.Form):
    store = forms.ModelChoiceField(queryset=None, label='Existing store')
    csv_file = forms.FileField(label='CSV v1 file', help_text='UTF-8 CSV, at most 5 MiB and 1,000 data rows. Keep all 25 headers.')
    nonce = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields['store'].queryset = available_stores(user)
        self.fields['nonce'].initial = signing.dumps({'user': user.pk, 'id': str(uuid.uuid4())}, salt='catalog-import-upload')
        for field in self.fields.values():
            if not field.widget.is_hidden:
                field.widget.attrs['class'] = 'form-select' if isinstance(field, forms.ModelChoiceField) else 'form-control'

    def clean_nonce(self):
        try:
            value = signing.loads(self.cleaned_data['nonce'], salt='catalog-import-upload', max_age=86400)
            if value['user'] != self.user.pk:
                raise ValueError
            return uuid.UUID(value['id'])
        except (signing.BadSignature, KeyError, ValueError, TypeError):
            raise forms.ValidationError('This upload form expired. Reload it before submitting.')

    def clean_csv_file(self):
        upload = self.cleaned_data['csv_file']
        if upload.size > MAX_CSV_BYTES or not upload.name.lower().endswith('.csv'):
            raise forms.ValidationError('Choose a CSV file no larger than 5 MiB.')
        return upload


class ImportApprovalForm(forms.Form):
    expected_hash = forms.RegexField(regex=r'^[0-9a-f]{64}$', widget=forms.HiddenInput)
    acknowledge = forms.BooleanField(label='I reviewed this exact preview and authorize its product creation, images and any displayed opening stock. Products remain pending publication approval.')
