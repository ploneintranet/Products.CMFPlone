from Products.CMFPlone import PloneMessageFactory as _
from Products.CMFPlone.interfaces.controlpanel import IImagingSchema
from logging import getLogger
from plone.app.registry.browser import controlpanel

log = getLogger('Plone')


class ImagingControlPanelForm(controlpanel.RegistryEditForm):

    id = "ImagingSettings"
    label = _(u"Imaging Settings")
    schema = IImagingSchema
    schema_prefix = "plone"


class ImagingControlPanel(controlpanel.ControlPanelFormWrapper):
    form = ImagingControlPanelForm
