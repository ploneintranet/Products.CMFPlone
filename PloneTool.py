from Products.CMFCore.utils import UniqueObject, getToolByName
from Products.CMFCore.utils import _checkPermission, _getAuthenticatedUser, limitGrantedRoles
from Products.CMFCore.utils import getToolByName, _dtmldir
from OFS.SimpleItem import SimpleItem
from Globals import InitializeClass, DTMLFile
from AccessControl import ClassSecurityInfo
from Products.CMFCore import CMFCorePermissions
from Products.CMFCore.interfaces.DublinCore import DublinCore
from types import TupleType
from urllib import urlencode
from cgi import parse_qs
import re

from zLOG import LOG, INFO
def log(summary='', text=''):
    LOG('Plone Debug', INFO, summary, text)

class PloneTool (UniqueObject, SimpleItem):
    id = 'plone_utils'
    meta_type= 'Plone Utility Tool'
    security = ClassSecurityInfo()
    plone_tool = 1
    field_prefix = 'field_' # Formulator prefixes for forms

    security.declarePublic('editMetadata')
    def editMetadata( self
                     , obj
                     , allowDiscussion=None
                     , title=None
                     , subject=None
                     , description=None
                     , contributors=None
                     , effective_date=None
                     , expiration_date=None
                     , format=None
                     , language=None
                     , rights=None
                     ,  **kwargs):
        """ responsible for setting metadata on a content object 
            we assume the obj implemented IDublinCoreMetadata 
        """
        REQUEST=self.REQUEST
        pfx=self.field_prefix
        def tuplify( value ):
            if not type(value) is TupleType:
                value = tuple( value )
            temp = filter( None, value )
            return tuple( temp )
        if title is None:
            title=REQUEST.get(pfx+'title', obj.Title())
        if subject is None:
            subject=REQUEST.get(pfx+'subject', obj.Subject())
        if description is None:
            description=REQUEST.get(pfx+'description', obj.Description())
        if contributors is None:
            contributors=tuplify(REQUEST.get(pfx+'contributors', obj.Contributors()))
        else:    
            contributors=tuplify(contributors)
        if effective_date is None:
            effective_date=REQUEST.get(pfx+'effective_date', obj.EffectiveDate())
        if expiration_date is None:
            expiration_date=REQUEST.get(pfx+'expiration_date', obj.ExpirationDate())
        if format is None:
            format=REQUEST.get('text_format', obj.Format())
        if language is None:
            language=REQUEST.get(pfx+'language', obj.Language())
        if rights is None:
            rights=REQUEST.get(pfx+'rights', obj.Rights())
        if allowDiscussion:
            allowDiscussion=allowDiscussion.lower().strip()
            if allowDiscussion=='default': allowDiscussion=None
            elif allowDiscussion=='off': allowDiscussion=0
            elif allowDiscussion=='on': allowDiscussion=1
            getToolByName(self, 'portal_discussion').overrideDiscussionFor(obj, allowDiscussion)
            
        obj.editMetadata( title=title
                        , description=description
                        , subject=subject
                        , contributors=contributors
                        , effective_date=effective_date
                        , expiration_date=expiration_date
                        , format=format
                        , language=language
                        , rights=rights )

    #XXX do we ever redirect?
    def _renameObject(self, obj, redirect=0, id=''):
        REQUEST=self.REQUEST
        if not id:
            id = REQUEST.get('id', '')
            id = REQUEST.get(self.field_prefix+'id', '')
        if id!=obj.getId():
            try:
                context.manage_renameObjects( (obj.getId(),), (id,), REQUEST )
            except: #XXX have to do this for Topics and maybe other folderish objects
                obj.aq_parent.manage_renameObjects( (obj.getId(),), (id,), REQUEST)
	if redirect:
            status_msg='portal_status_message='+REQUEST.get( 'portal_status_message', 'Changes+have+been+Saved.')
            return REQUEST.RESPONSE.redirect('%s/%s?%s' % ( REQUEST['URL2'], id, status_msg) )

    def _makeTransactionNote(self, obj, msg=''):
        #XXX why not aq_parent()?
        relative_path='/'.join(getToolByName(self, 'portal_url').getRelativeContentPath(obj)[:-1])
        if not msg:
            msg=relative_path+'/'+obj.title_or_id()+' has been modified.'
        get_transaction().note(msg)

    security.declarePublic('contentEdit')
    def contentEdit(self, obj, **kwargs):
        """ encapsulates how the editing of content occurs """

        #XXX Interface package appears to be broken.  Atleast for Forum objects.
        #    it may blow up on things that *done* implement the DublinCore interface. 
        #    Someone please look into this.  We should probably catch the exception (think its Tuple error)
        #    instead of swallowing all exceptions.
        try:
            if DublinCore.isImplementedBy(obj):
                apply(self.editMetadata, (obj,), kwargs)
        except: 
            pass
        
        if kwargs.get('id', None) is not None: 
            self._renameObject(obj, id=kwargs['id'].strip()) 
	
        self._makeTransactionNote(obj) #automated the manual transaction noting in xxxx_edit.py

    security.declarePublic('availableMIMETypes')
    def availableMIMETypes(self):
        """ Return a map of mimetypes """
        # This should probably be done in a more efficent way.
        import mimetypes
        
        result = []
        for mimetype in mimetypes.types_map.values():
            if not mimetype in result:
                result.append(mimetype)

        result.sort()
        return result

    security.declareProtected(CMFCorePermissions.View, 'getWorkflowChainFor')
    def getWorkflowChainFor(self, object):
        """ Proxy the request for the chain to the workflow
            tool, as this method is private there.
        """
        wftool = getToolByName(self, 'portal_workflow')
        wfs=()
        try:
            wfs=wftool.getChainFor(object)
        except: #XXX ick
            pass 
        return wfs

    # Transitions are determined by a set of actions listed in a properties file.
    # One can include information from the REQUEST into a transition by using 
    # an expression enclosed in brackets, i.e. something of the form [foo].
    # The bracketed expression will be replaced by REQUEST['foo'], or an empty
    # string if the REQUEST has no key 'foo'.  To specify an alternative action
    # in the event that the REQUEST has no key 'foo', use [foo|bar].  If REQUEST.foo
    # doesn't exist, then the bracketed expression is replaced by bar.
    #
    # Example: document.document_edit.success:string=view?came_from=[came_from|/]
    #
    # Regular expression used for performing substitutions in navigation transitions:
    # Find a [ that is not prefixed by a \, then
    # get everything until we hit a ] not prefixed by a \,
    # then get the terminal ]
    transitionSubExpr = r"""(?:(?<!\\)\[)(?P<expr>(?:[^\]]|(?:(?<=\\)\]))*)(?:(?<!\\)\])"""
    transitionSubReg = re.compile(transitionSubExpr, re.VERBOSE)

    def _transitionSubstitute(self, action, REQUEST):
        action2 = ''
        segments = self.transitionSubReg.split(action)
        count = 0
        for seg in segments:
            if count % 2:
                separatorIndex = seg.find('|')
                if separatorIndex >= 0:
                    key = seg[0:separatorIndex]
                    fallback = seg[separatorIndex+1:]
                else:
                    key = seg
                    fallback = ''
                action2 = action2 + REQUEST.get(key, fallback)
            else:
                action2 = action2 + seg
            count = count + 1
        action2 = action2.replace('\[', '[')
        action2 = action2.replace('\]', ']')
        return action2

    def getNavigationTransistion(self, context, action, status):
        navprops = getattr(self, 'navigation_properties')
        fixedTypeName = ''.join(context.getTypeInfo().getId().lower().split(' '))
        navTransition = fixedTypeName+'.'+action+'.'+status
        action_id = getattr(navprops.aq_explicit, navTransition, None)
        if action_id is None:
            navTransition='%s.%s.%s' % ('default',action,status)
            action_id = getattr(navprops.aq_explicit, navTransition, None)
        if action_id is None:
            navTransition='%s.%s.%s' % ('default','default',status)
            action_id = getattr(navprops.aq_explicit, navTransition, '')
        return self._transitionSubstitute(action_id, self.REQUEST)

    security.declarePublic('getNextPageFor')
    def getNextPageFor(self, context, action, status, **kwargs):
        """ given a object, action_id and status we can fetch the next action
            for this object 
        """
        action_id=self.getNavigationTransistion(context,action,status)
        # If any query parameters have been specified in the transition,
        # stick them into the request before calling getActionById()
        queryIndex = action_id.find('?')
        if queryIndex > -1:
            query = parse_qs(action_id[queryIndex+1:])
            for key in query.keys():
                if len(query[key]) == 1:
                    self.REQUEST[key] = query[key][0]
                else:
                    self.REQUEST[key] = query[key]
            action_id = action_id[0:queryIndex]
        next_action=context.getTypeInfo().getActionById(action_id)
        if next_action is not None:
            return context.restrictedTraverse(next_action)
        raise Exception, 'Argh! could not find the transition, ' + navTransition
            
    security.declarePublic('getNextRequestFor')
    def getNextRequestFor(self, context, action, status, **kwargs):
        """ takes object, action, and status and returns a RESPONSE redirect """
        action_id=self.getNavigationTransistion(context,action,status) ###
        if action_id.find('?') >= 0:
            separator = '&'
        else:
            separator = '?'
            
        url_params=urlencode(kwargs)
        redirect=None
        try:
            action_id=context.getTypeInfo().getActionById(action_id)
        except: # XXX because ActionTool doesnt throw ActionNotFound exception ;(
            pass
        return self.REQUEST.RESPONSE.redirect( '%s/%s%s%s' % ( context.absolute_url()
                                                             , action_id
                                                             , separator
                                                             , url_params) )
InitializeClass(PloneTool)

