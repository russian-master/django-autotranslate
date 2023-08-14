import collections
import six
import requests

from autotranslate.compat import goslate, googleapiclient

from django.conf import settings


class BaseTranslatorService:
    """
    Defines the base methods that should be implemented
    """

    def translate_string(self, text, target_language, source_language='en'):
        """
        Returns a single translated string literal for the target language.
        """
        raise NotImplementedError('.translate_string() must be overridden.')

    def translate_strings(self, strings, target_language, source_language='en', optimized=True):
        """
        Returns a iterator containing translated strings for the target language
        in the same order as in the strings.
        :return:    if `optimized` is True returns a generator else an array
        """
        raise NotImplementedError('.translate_strings() must be overridden.')


class GoSlateTranslatorService(BaseTranslatorService):
    """
    Uses the free web-based API for translating.
    https://bitbucket.org/zhuoqiang/goslate
    """

    def __init__(self):
        assert goslate, '`GoSlateTranslatorService` requires `goslate` package'
        self.service = goslate.Goslate()

    def translate_string(self, text, target_language, source_language='en'):
        assert isinstance(text, six.string_types), '`text` should a string literal'
        return self.service.translate(text, target_language, source_language)

    def translate_strings(self, strings, target_language, source_language='en', optimized=True):
        assert isinstance(strings, collections.Iterable), '`strings` should a iterable containing string_types'
        translations = self.service.translate(strings, target_language, source_language)
        return translations if optimized else [_ for _ in translations]


class GoogleAPITranslatorService(BaseTranslatorService):
    """
    Uses the paid Google API for translating.
    https://github.com/google/google-api-python-client
    """

    def __init__(self, max_segments=128):
        assert googleapiclient, '`GoogleAPITranslatorService` requires `google-api-python-client` package'

        self.developer_key = getattr(settings, 'GOOGLE_TRANSLATE_KEY', None)
        assert self.developer_key, ('`GOOGLE_TRANSLATE_KEY` is not configured, '
                                    'it is required by `GoogleAPITranslatorService`')

        from googleapiclient.discovery import build
        self.service = build('translate', 'v2', developerKey=self.developer_key)

        # the google translation API has a limit of max
        # 128 translations in a single request
        # and throws `Too many text segments Error`
        self.max_segments = max_segments
        self.translated_strings = []

    def translate_string(self, text, target_language, source_language='en'):
        assert isinstance(text, six.string_types), '`text` should a string literal'
        response = self.service.translations() \
            .list(source=source_language, target=target_language, q=[text]).execute()
        return response.get('translations').pop(0).get('translatedText')

    def translate_strings(self, strings, target_language, source_language='en', optimized=True):
        assert isinstance(strings, collections.abc.MutableSequence), \
            '`strings` should be a sequence containing string_types'
        assert not optimized, 'optimized=True is not supported in `GoogleAPITranslatorService`'
        if len(strings) == 0:
            return []
        elif len(strings) <= self.max_segments:
            setattr(self, 'translated_strings', getattr(self, 'translated_strings', []))
            response = self.service.translations() \
                .list(source=source_language, target=target_language, q=strings).execute()
            self.translated_strings.extend([t.get('translatedText') for t in response.get('translations')])
            return self.translated_strings
        else:
            self.translate_strings(strings[0:self.max_segments], target_language, source_language, optimized)
            _translated_strings = self.translate_strings(strings[self.max_segments:],
                                                         target_language, source_language, optimized)

            # reset the property or it will grow with subsequent calls
            self.translated_strings = []
            return _translated_strings


class YandexAPITranslatorService(BaseTranslatorService):
    """
    Uses the Yandex Cloud API for translating.
    """

    def __init__(self):
        self.api_url = 'https://translate.api.cloud.yandex.net/translate/v2/translate'
        self.iam_token = getattr(settings, 'YANDEX_IAM_TOKEN', None)
        self.folder_id = getattr(settings, 'YANDEX_FOLDER_ID', None)
        
        # Check if token and folder_id are configured
        assert self.iam_token and self.folder_id, ('`YANDEX_IAM_TOKEN` and `YANDEX_FOLDER_ID` are required for `YandexAPITranslatorService`')

    def translate_string(self, text, target_language, source_language='en'):
        # Translate a single string
        translated_text = self.translate_strings([text], target_language, source_language)
        return translated_text[0] if translated_text else text

    def translate_strings(self, strings, target_language, source_language='en', optimized=True):
        body = {
            "targetLanguageCode": target_language,
            "texts": strings,
            "folderId": self.folder_id,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {0}".format(self.iam_token)
        }

        response = requests.post(self.api_url, json=body, headers=headers)
        response_data = response.json()

        # Extract translated texts from the response and return
        translations = [item['text'] for item in response_data.get('translations', [])]
        return translations