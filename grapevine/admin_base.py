from __future__ import unicode_literals
from collections import OrderedDict
import json

# Django
from django.contrib import admin, messages
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.conf.urls import patterns, url
from django.core.urlresolvers import reverse, NoReverseMatch
from django.shortcuts import get_object_or_404
from django.contrib.contenttypes.models import ContentType

# Local Apps
from .forms import AdminBulkEditForm
from grapevine.emails.filters import OnSpecificDateListFilter
from grapevine.utils import render_view


class BaseModelAdmin(admin.ModelAdmin):

    additional_object_tool_excludes = ()

    @property
    def model_meta_info(self):
        return (self.model._meta.app_label, self.model._meta.model_name,)

    @property
    def admin_view_info(self):
        return '%s_%s' % self.model_meta_info

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if obj:
            context['additional_object_tools'] = self.additional_object_tools(obj)
        return super(BaseModelAdmin, self).render_change_form(request, context, add, change, form_url, obj)

    def additional_object_tools(self, obj):
        tool_urls = []
        excludes = self.get_additional_object_tool_excludes(obj)
        for relationship in obj._meta.get_all_related_objects():
            # Skip all excludes
            if relationship.get_accessor_name() in excludes:
                continue

            remote_field_name = relationship.field.name
            try:
                url = reverse('admin:%s_%s_changelist' % (relationship.model._meta.app_label, relationship.model._meta.model_name,))
                url += '?%s=%s' % (remote_field_name, obj.pk,)

                display_name = "View %s" % (relationship.get_accessor_name().title(),)
                display_name = display_name.replace('_', ' ')
                tool_urls.append({
                    'url': url,
                    'display_name': display_name
                })
            except NoReverseMatch:
                pass

        return tool_urls

    def get_additional_object_tool_excludes(self, obj):
        """
        Returns an interable of relationship ``get_accessor_name()`` values that should **not** be automatically
        added to the additional tools section in the admin.

        Generally speaking, ``get_accessor_name()`` returns the name of the ReverseManager,
        which is what is overwritten by the ``related_name`` keyword on ForeignKey fields.
        """
        return self.additional_object_tool_excludes


class SendableInline(admin.TabularInline):

    fields = ["admin_id", "admin_message", "scheduled_send_time", "cancelled_at_send_time"]

    def admin_id(self, obj):
        url = reverse('admin:%s_change' % (obj.admin_view_info,), args=(obj.id,))
        return '<a href="%s" target="_blank">%s</a>' % (url, obj.id,)
    admin_id.allow_tags = True
    admin_id.short_description = 'Id'

    def admin_message(self, obj):
        if obj.message is None:
            return '--'

        transport_class_app_name = obj.get_transport_class()._meta.app_label
        transport_class_sluggy_name = obj.get_transport_class()._meta.verbose_name.lower().replace(' ', '_')
        url = reverse('admin:%s_%s_change' % (transport_class_app_name, transport_class_sluggy_name,), args=(obj.message_id,))
        return '<a href="%s" target="_blank" style="text-decoration:none;">%s</a>' % (url, obj.message.__unicode__(),)
    admin_message.allow_tags = True
    admin_message.short_description = 'Message'

    def has_delete_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request, obj=None):
        return True

    readonly_fields = ['admin_id', 'admin_message']
    extra = 0


class SendableAdminMixin(object):
    """
    You must set `model` in any Admin classes inheriting from this
    class or nothing will work.
    """
    # Used for admin display purposes
    message_type_verbose = "Message"

    readonly_fields = ['admin_message']
    list_filter = (('scheduled_send_time', OnSpecificDateListFilter),)

    change_form_template = 'admin/change_sendable_form.html'

    def lookup_allowed(self, key, value):
        """
        Normally list filtering is only *allowed* on things specified in
        ``list_filter`` above, but that's a problem because the Django admin
        wants to draw a dropdown containing all possible options. To search
        on ``model__related_model``, we would have to specify exactly that, and Django
        might try to draw a dropdown of all umpteen million records. No bien.

        Thus, we whitelist some fields ourselves as being legal edits without
        specifying them in the place where a fckng mammoth <select> field could result.
        """
        for field_name in self.whitelisted_filter_fields:
            if field_name in key:
                return True
        return super(SendableAdminMixin, self).lookup_allowed(key, value)

    def admin_message(self, obj):
        if obj.message is None:
            return '--'

        transport_class_app_name = obj.get_transport_class()._meta.app_label
        transport_class_sluggy_name = obj.get_transport_class()._meta.verbose_name.lower().replace(' ', '_')
        url = reverse('admin:%s_%s_change' % (transport_class_app_name, transport_class_sluggy_name,), args=(obj.message_id,))
        return '<a href="%s" target="_blank" style="text-decoration:none;">%s</a>' % (url, obj.message.__unicode__(),)
    admin_message.allow_tags = True
    admin_message.short_description = 'Message'

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if obj:
            # Get the preview URL
            view_name = 'admin:%s_render' % (self.admin_view_info,)
            context['preview_url'] = reverse(view_name, args=(obj.pk,))

            # Add in the message type, for nice clarity across various types of transports
            context['message_type_verbose'] = self.message_type_verbose
        return super(SendableAdminMixin, self).render_change_form(request, context, add, change, form_url, obj)

    def additional_object_tools(self, obj):
        tools = super(SendableAdminMixin, self).additional_object_tools(obj)
        tools.append({
            'url': reverse('admin:%s_send_test_message' % (self.admin_view_info,), args=(obj.pk,)),
            'display_name': 'Send Test %s' % (self.message_type_verbose,)
        })
        if not obj.is_sent or not obj.message or obj.message.status != obj.message.SENT:
            tools.append({
                'url': reverse('admin:%s_send_real_message' % (self.admin_view_info,), args=(obj.pk,)),
                'display_name': 'Send Real %s' % (self.message_type_verbose,)
            })
        return tools

    @property
    def model_meta_info(self):
        return (self.model._meta.app_label, self.model._meta.model_name,)

    @property
    def admin_view_info(self):
        return '%s_%s' % self.model_meta_info

    def get_urls(self):
        urls = super(SendableAdminMixin, self).get_urls()
        my_urls = [
            url(r'^(.+)/render/$', self.admin_site.admin_view(self.render), name='%s_render' % (self.admin_view_info,)),
            url(r'^(.+)/send-test/$', self.admin_site.admin_view(self.send_test_message), name='%s_send_test_message' % (self.admin_view_info,)),
            url(r'^(.+)/send-real/$', self.admin_site.admin_view(self.send_real_message), name='%s_send_real_message' % (self.admin_view_info,)),
        ]
        return my_urls + urls

    def send_real_message(self, request, obj_id):
        obj = get_object_or_404(self.model, pk=obj_id)
        if request.method == 'GET':
            context = {
                'obj': obj,
                'recipients': obj.get_recipients(),
                'opts': self.model._meta,
                'title': 'Send Real %s' % (self.message_type_verbose,)
            }
            return render_view(request, 'grapevine/emails/templates/admin/send_real.html', context)
        elif request.method == 'POST':
            return self.send_message(request, obj, False)

    def send_test_message(self, request, obj_id):
        obj = get_object_or_404(self.model, pk=obj_id)
        if request.method == 'GET':
            context = {
                'recipients': self.get_test_recipient(request, obj_id),
                'opts': self.model._meta,
                'title': 'Send Test %s' % (self.message_type_verbose,)
            }
            return render_view(request, 'grapevine/emails/templates/admin/send_test.html', context)
        elif request.method == 'POST':
            return self.send_message(request, obj, True, request.POST.get('recipient_address'))

    def get_test_recipient(self, request, obj_id):
        """
        No idea what makes sense against a generic Sendable
        """
        return ''

    def send_message(self, request, obj, is_test, recipient_address=None):
        if not request.user.is_authenticated() or not request.user.is_staff:
            raise Http404

        if is_test and not request.user.email:
            messages.add_message(request, messages.ERROR,
                "Current Admin user does not have a specified email address.")
            return HttpResponseRedirect(reverse("admin:%s_change" % (self.admin_view_info,), args=(obj.pk,)))

        # Load the Sendable and send a message
        is_sent = obj.send(recipient_address=recipient_address, is_test=is_test)

        if is_sent:
            message_beginning = 'Test' if is_test else ''
            message_ending = 'to %s' % (recipient_address) if recipient_address else ''
            messages.add_message(request, messages.SUCCESS,
                "%s Message sent %s" % (message_beginning, message_ending,))

            content_type_id = ContentType.objects.get_for_model(obj).pk
            admin.models.LogEntry.objects.log_action(
                user_id=request.user.pk,
                content_type_id=content_type_id,
                object_id=obj.pk,
                object_repr=obj.__unicode__(),
                action_flag=admin.models.CHANGE,
                change_message='Sent %s Message Id: %s for %s Id: %s' % (message_beginning, obj.transport.pk, obj._meta.verbose_name, obj.pk,)
            )
        else:
            messages.add_message(request, messages.ERROR,
                "Problem sending email.")

        return HttpResponseRedirect(reverse('admin:%s_change' % (self.admin_view_info,), args=(obj.pk,)))

    def render(self, request, obj_id):
        if not request.user.is_authenticated() or not request.user.is_staff:
            raise Http404

        obj = get_object_or_404(self.model, pk=obj_id)
        try:
            return HttpResponse(obj.render())
        except Exception as e:
            return HttpResponse("%s: %s" % (e.__class__.__name__, e.args[0],))


class FreezableTemplateAdminMixin(SendableAdminMixin):
    """
    Provides an interface for models that extend
    mixins.TemplateFreezableSendableMixin
    """
    actions = ['action_bulk_edit']
    whitelisted_filter_fields = ()

    def action_bulk_edit(self, request, queryset):
        """
        The function that (mostly) powers the Bulk Edits action. Ultimately
        just draws the form that redirects to ``self.perform_bulk_edits``.
        """
        objs_by_date = OrderedDict()
        for obj in queryset.order_by('scheduled_send_time'):
            try:
                formatted_date = obj.scheduled_send_time.strftime("%B %d, %Y")
            except:
                formatted_date = "Unscheduled"
            objs_by_date.setdefault(formatted_date, [])
            objs_by_date[formatted_date].append(obj)

        context = {
            'request': request,
            'queryset': queryset,
            'model': self.model,
            'objs_by_date': objs_by_date,
            'form_url_action': reverse('admin:%s_bulkedits' % (self.admin_view_info,)),
            'bulk_edit_form': self.get_bulk_edit_form(request)
        }
        return render_view(request, 'admin/bulk_edits.html', context)
    action_bulk_edit.short_description = 'Bulk Edit'

    def get_bulk_edit_form(self, request):
        return AdminBulkEditForm

    def perform_bulk_edits(self, request):
        if not request.user.is_authenticated() and request.user.is_staff:
            return HttpResponse(status=401)

        if request.method != 'POST':
            return HttpResponse(status=405)

        bulk_edit_ids = request.POST.getlist('bulk_edit_obj_id')
        bulk_edit_objs = self.model.objects.filter(pk__in=bulk_edit_ids)

        form = self.get_bulk_edit_form(request)(request.POST)
        # This is required to combine the date and time widgets back
        # into the singular `scheduled_send_time` value.
        form.full_clean()

        update_dict = {}
        log_dict = {}
        for field_name, value in form.cleaned_data.items():
            if value:
                update_dict[field_name] = value
                log_dict[field_name] = value.__repr__()

        if update_dict:
            bulk_edit_objs.update(**update_dict)

            sr_ct_id = ContentType.objects.get_for_model(self.model).pk
            # Log each change to the admin. TRACEABILITY FTW!
            for sr in bulk_edit_objs:
                admin.models.LogEntry.objects.log_action(
                    user_id=request.user.pk,
                    content_type_id=sr_ct_id,
                    object_id=sr.pk,
                    object_repr=sr.__unicode__(),
                    action_flag=admin.models.CHANGE,
                    change_message='Applied %s to %s %s Id: %s' % (json.dumps(log_dict), 'SENT' if sr.message_id else 'UNSENT', self.model._meta.verbose_name, sr.pk,)
                )

        messages.add_message(request, messages.SUCCESS,
            "%s messages updated successfully." % (len(bulk_edit_ids),))

        return HttpResponseRedirect('/admin/%s/%s/' % self.model_meta_info)

    def freeze_template(self, request, obj_id):
        if not request.user.is_authenticated() or not request.user.is_staff:
            raise Http404

        obj = get_object_or_404(self.model, pk=obj_id)
        obj.freeze_template()

        content_type_id = ContentType.objects.get_for_model(obj).pk
        admin.models.LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=content_type_id,
            object_id=obj_id,
            object_repr=obj.__unicode__(),
            action_flag=admin.models.CHANGE,
            change_message='Froze TemplateId:%s for customization' % (obj.template_id,)
        )

        return HttpResponseRedirect(reverse('admin:%s_change' % (self.admin_view_info,), args=(obj_id,)))

    def additional_object_tools(self, obj):
        tools = super(FreezableTemplateAdminMixin, self).additional_object_tools(obj)

        freeze_url_name = 'admin:%s_freeze' % (self.admin_view_info,)
        tools.append({
            'url': reverse(freeze_url_name, args=(obj.pk,)),
            'display_name': 'Freeze Template for Customization'
        })
        return tools

    def get_urls(self):
        urls = super(FreezableTemplateAdminMixin, self).get_urls()
        my_urls = patterns('',
            url(r'^bulk_edits/$', self.admin_site.admin_view(self.perform_bulk_edits), name='%s_bulkedits' % (self.admin_view_info,)),
            url(r'^(.+)/freeze-template/$', self.admin_site.admin_view(self.freeze_template), name='%s_freeze' % (self.admin_view_info,)),
        )
        return my_urls + urls