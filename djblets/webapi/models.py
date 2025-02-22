from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from djblets.db.fields import JSONField, ModificationTimestampField
from djblets.webapi.managers import WebAPITokenManager
from djblets.webapi.signals import webapi_token_updated


class BaseWebAPIToken(models.Model):
    """Base class for an access token used for authenticating with the API.

    Each token can be used to authenticate the token's owner with the API,
    without requiring a username or password to be provided. Tokens can
    be revoked, and new tokens added.

    Tokens can store policy information, which will later be used for
    restricting access to the API.
    """

    user = models.ForeignKey(
        User,
        related_name='webapi_tokens',
        on_delete=models.CASCADE,
        help_text=_('The user that owns the token.'))

    token = models.CharField(
        max_length=255,
        unique=True,
        help_text=_('The access token.'))
    token_generator_id = models.CharField(
        max_length=255,
        help_text=_('The token generator that generated the token.'))
    time_added = models.DateTimeField(
        default=timezone.now,
        help_text=_('The date and time when the token was first added '
                    'to the database.'))
    last_updated = ModificationTimestampField(
        default=timezone.now,
        help_text=_('The date and time when the token was last updated.'))
    last_used = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('The date and time when the token was last used '
                    'for authentication.'))
    expires = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('An optional field for the date and time that the token '
                    'will expire. The token will be invalid and unusable '
                    'for authentication after this point.'))

    valid = models.BooleanField(
        default=True,
        help_text=_('Whether the token is currently valid.'))
    invalid_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('The date and time at which the token became invalid.'))
    invalid_reason = models.TextField(
        blank=True,
        help_text=_('A message indicating why the token is no longer valid.'))

    note = models.TextField(
        blank=True,
        help_text=_('A message describing the token.'))
    policy = JSONField(
        null=True,
        help_text=_('The policy document describing what this token can '
                    'access in the API. If empty, this provides full access.'))

    extra_data = JSONField(null=True)

    objects = WebAPITokenManager()

    def is_accessible_by(self, user):
        return user.is_superuser or self.user == user

    def is_mutable_by(self, user):
        return user.is_superuser or self.user == user

    def is_deletable_by(self, user):
        return user.is_superuser or self.user == user

    def is_expired(self):
        """Returns whether the token is expired or not.

        Version Added:
            3.0

        Returns:
            bool:
            Whether the token is expired. This will be ``False`` if there
            is no expiration date set.
        """
        return self.expires is not None and timezone.now() >= self.expires

    def __str__(self):
        return 'Web API token for %s' % self.user

    def save(self, *args, **kwargs):
        """Save the token.

        If the token is being updated, the
        :py:data:`~djblets.webapi.signals.webapi_token_updated` signal will be
        emitted.

        Args:
            *args (tuple):
                Positional arguments to pass to the superclass.

            **kwargs (dict):
                Keyword arguments to pass to the superclass.
        """
        is_new = self.pk is None

        super().save(*args, **kwargs)

        if not is_new:
            webapi_token_updated.send(instance=self, sender=type(self))

    @classmethod
    def get_root_resource(cls):
        raise NotImplementedError

    @classmethod
    def validate_policy(cls, policy):
        """Validate an API policy.

        This will check to ensure that the policy is in a suitable format
        and contains the information required in a format that can be parsed.

        If a failure is found, a ValidationError will be raised describing
        the error and where it was found.
        """
        if not isinstance(policy, dict):
            raise ValidationError(_('The policy must be a JSON object.'))

        if not policy:
            # Empty policies are equivalent to allowing full access. If this
            # is empty, we can stop here.
            return

        if 'resources' not in policy:
            raise ValidationError(
                _('The policy is missing a "resources" section.'))

        resources_section = policy['resources']

        if not isinstance(resources_section, dict):
            raise ValidationError(
                _('The policy\'s "resources" section must be a JSON object.'))

        if not resources_section:
            raise ValidationError(
                _('The policy\'s "resources" section must not be empty.'))

        if '*' in resources_section:
            cls._validate_policy_section(resources_section, '*',
                                         'resources.*')

        resource_policies = [
            (section_name, section)
            for section_name, section in resources_section.items()
            if section_name != '*'
        ]

        if resource_policies:
            valid_policy_ids = \
                cls._get_valid_policy_ids(cls.get_root_resource())

            for policy_id, section in resource_policies:
                if policy_id not in valid_policy_ids:
                    raise ValidationError(
                        _('"%s" is not a valid resource policy ID.')
                        % policy_id)

                for subsection_name, subsection in section.items():
                    if not isinstance(subsection_name, str):
                        raise ValidationError(
                            _('%s must be a string in "resources.%s"')
                            % (subsection_name, policy_id))

                    cls._validate_policy_section(
                        section, subsection_name,
                        'resources.%s.%s' % (policy_id, subsection_name))

    @classmethod
    def _validate_policy_section(cls, parent_section, section_name,
                                 full_section_name):
        section = parent_section[section_name]

        if not isinstance(section, dict):
            raise ValidationError(
                _('The "%s" section must be a JSON object.')
                % full_section_name)

        if 'allow' not in section and 'block' not in section:
            raise ValidationError(
                _('The "%s" section must have "allow" and/or "block" '
                  'rules.')
                % full_section_name)

        if 'allow' in section and not isinstance(section['allow'], list):
            raise ValidationError(
                _('The "%s" section\'s "allow" rule must be a list.')
                % full_section_name)

        if 'block' in section and not isinstance(section['block'], list):
            raise ValidationError(
                _('The "%s" section\'s "block" rule must be a list.')
                % full_section_name)

    @classmethod
    def _get_valid_policy_ids(cls, resource, result=None):
        if result is None:
            result = set()

        if hasattr(resource, 'policy_id'):
            result.add(resource.policy_id)

        for child_resource in resource.list_child_resources:
            cls._get_valid_policy_ids(child_resource, result)

        for child_resource in resource.item_child_resources:
            cls._get_valid_policy_ids(child_resource, result)

        return result

    class Meta:
        abstract = True
        verbose_name = _('Web API token')
        verbose_name_plural = _('Web API tokens')
