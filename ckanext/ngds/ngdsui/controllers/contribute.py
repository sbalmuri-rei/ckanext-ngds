from ckan.lib.base import *
from ckan.lib.navl.dictization_functions import DataError, unflatten, validate
from ckan.lib.base import (request,
                           render,
                           model,
                           abort, h, g, c)
from ckan.logic import (tuplize_dict,clean_dict,
                        parse_params,flatten_to_string_key,get_action,check_access,NotAuthorized)
from pylons import config
from ckanext.ngds.ngdsui.controllers.ngds import NGDSBaseController
import ckanext.ngds.lib.importer.helper as import_helper

import os
import shutil
import zipfile
import os.path

class ContributeController(NGDSBaseController):

 	def index(self):
		
		"""
		Renders contribute page.
		"""

		if g.central:
			nodes = model.HarvestNode.get_all()
			c.harvested_nodes = nodes

		return render('contribute/contribute.html')		

	def harvest(self):
		"""
		Create new Harvest node.
		"""
		c.action = 'save'
		return render('contribute/harvest_new.html')

	def upload(self):
		"""
		Render the upload page
		"""

		return render('contribute/upload.html')

	def bulk_upload(self):

		context = {'model': model, 'session': model.Session,'user': c.user or c.author}

		try:
			check_access('package_create',context,None)
		except NotAuthorized, error:
			abort(401,error.__str__())		

		return render('contribute/bulkupload_form.html')

	def bulk_upload_handle(self):
		"""	
		Handles the bulk upload of datasets. Recieves the dataset file and zip file as part of the request and validates them.
		"""
		context = {'model': model, 'session': model.Session,'user': c.user or c.author}

		try:
			check_access('package_create',context,None)
		except NotAuthorized, error:
			abort(401,error.__str__())	

		#Validate the dataset file.

		bulk_dir = config.get('ngds.bulk_upload_dir')

		from datetime import datetime
		ts = datetime.isoformat(datetime.now()).replace(':','').split('.')[0]

		upload_dir = os.path.join(bulk_dir, ts)

		if not os.path.exists(upload_dir):
			os.makedirs(upload_dir)


		# Recieve the dataset file to be processed.
		datasetfile = request.POST['datasetfile']

		if datasetfile == "":
			#raise Exception (_("Data file can't be empty."))
			abort(500,_("Data file can't be empty."))	


		datafilename = datasetfile.filename		

		datafilepath =os.path.join(upload_dir,datasetfile.filename.replace(os.sep, '_'))

		permanent_data_file = open(datafilepath,'wb')		
		shutil.copyfileobj(datasetfile.file, permanent_data_file )		
		datasetfile.file.close()		
		permanent_data_file.close()		



		resourcefile = request.POST['resourceszip']
		resource_list = None
		resourcesfilename = None

		if resourcefile !="":
			resourcesfilename = resourcefile.filename
			resfilepath =os.path.join(upload_dir,resourcefile.filename.replace(os.sep, '_'))
			permanent_zip_file = open(resfilepath,'wb')
			shutil.copyfileobj(resourcefile.file, permanent_zip_file )
			resourcefile.file.close()
			permanent_zip_file.close()


			zfile = zipfile.ZipFile(resfilepath)
			

			zfile.extractall(path=upload_dir)

			def dir_filter(s):
				if os.path.isdir(os.path.join(upload_dir,s)):
					return False
	   			return True

			
			resource_list = filter(dir_filter,zfile.namelist())


		status,err_msg = self._validate_uploadfile(datafilepath,upload_dir,resource_list)


		if status == "INVALID":
			import_helper.delete_files(file_path=upload_dir,ignore_files=[datafilename,resourcesfilename])


		self._create_bulk_upload_record(c.user or c.author,datafilename,resourcesfilename,upload_dir,status,err_msg)

		url = h.url_for(controller='ckanext.ngds.ngdsui.controllers.contribute:ContributeController', action='bulk_upload')
		redirect(url)		


	def _validate_uploadfile(self,data_file,resource_path,resource_list):

		#import ckanext.ngds.lib.importer.validator.NGDSValidator
		import ckanext.ngds.lib.importer.validator as validator
		err_msg = ""            		
		try:
			validator = validator.NGDSValidator(filepath=data_file,resource_path=resource_path,resource_list=resource_list)
			validator.validate()
			status="VALID"
			h.flash_notice(_('Files Uploaded Successfully.'), allow_html=True)
		except Exception, e:
			err_msg = e.__str__()
			h.flash_error(_('Files Uploaded but it is invalid. Error: "%s" '%err_msg), allow_html=True)
			status ="INVALID"

		return status,err_msg

	def _create_bulk_upload_record(self,user,data_file,resources,path,status,comments):
		#print "inside _create_bulk_upload_record:",c.user

		userObj = model.User.by_name(c.user.decode('utf8'))

		data = {'data_file':data_file,'resources':resources,'path':path,'status':status,'comments':comments,'uploaded_by':userObj.id}
		data_dict = {'model':'BulkUpload'}
		data_dict['data']=data
		data_dict['process']='create'

		#print "Data dict: ",data_dict

		context = {'model': model, 'session': model.Session,'user': c.user or c.author}

		transaction_return = get_action('transaction_data')(context, data_dict)					

		#print "transaction_return:",transaction_return

	def edit(self,id):
		"""
		Editing the existing Harvest node.
		"""
		context = {'model': model, 'session': model.Session,'user': c.user or c.author}

		try:
			check_access('manage_nodes',context,None)
		except NotAuthorized, error:
			abort(401,error.__str__())

		c.isEdit = True
		c.action = 'edit_save'
		c.node = self._read_node(id)
		return render('contribute/harvest_edit.html')	

	def edit_save(self,id=None):
		"""
		Updating the edited  Harvest node.
		"""

		context = {'model': model, 'session': model.Session,'user': c.user or c.author}

		try:
			check_access('manage_nodes',context,None)
		except NotAuthorized, error:
			abort(401,error.__str__())


		data = clean_dict(unflatten(tuplize_dict(parse_params(
            request.params))))	

		node_id = data['id'] or id

		print "Data Dict Values on Edit: " ,data

		#Update responsible Party

		data['id'] = data['node_admin_id']

		res_party_data = self.update_responsible_party(data)

		#Update Node Admin ID just to make sure if it is updated as part of edit. TODO: Handle new Responsible party creation
		data['node_admin_id'] = res_party_data['id']
		data['id'] = node_id

		data_dict = {'model':'HarvestNode'}
		data_dict['data']=data
		data_dict['process']='update'
		
		context = {'model': model}

		get_action('ngds_harvest')(context, data_dict)		

		#return self.read(node_id)

		print " Node ID: ", node_id

		url = h.url_for(controller='ckanext.ngds.ngdsui.controllers.contribute:ContributeController', action='edit', id=node_id)
		redirect(url)

	def save(self,data=None):
		"""
		Create new Harvest node.
		"""

		#harvestNode = model.HarvestNode

		data = clean_dict(unflatten(tuplize_dict(parse_params(
            request.params))))							

		data_dict = self.create_responsible_party(data)
		data['node_admin_id'] = data_dict['id']

		"""	
		harvestNode.url = data['url']
		harvestNode.frequency = data['frequency']
		harvestNode.title = data['title']
		harvestNode.node_admin_id = data['node_admin_id']
			
		print "Harvest the data: ",harvestNode

		harvestNode.save()
		"""
		data_dict = {'model':'HarvestNode'}
		data_dict['data']=data
		data_dict['process']='create'

		print "Data dict: ",data_dict

		context = {'model': model}

		get_action('ngds_harvest')(context, data_dict)		


		#return self.index()
		url = h.url_for(controller='ckanext.ngds.ngdsui.controllers.contribute:ContributeController', action='index')
		redirect(url)		

	def delete(self,id):

		"""
		Deletes Harvest node.
		"""

		data_dict = {'model':'HarvestNode'}
		data_dict['data']={'id':id}
		data_dict['process']='delete'

		print "Data dict: ",data_dict

		context = {'model': model}

		get_action('ngds_harvest')(context, data_dict)		

		url = h.url_for(controller='ckanext.ngds.ngdsui.controllers.contribute:ContributeController', action='index')
		redirect(url)		

 	def read(self,id):
		
		"""
		Fetches the details about a particular node.
		"""

		node = self._read_node(id)

		c.node = node

		return render('contribute/harvest_read.html')

	def _read_node(self,id):
	
		node = 	model.HarvestNode.by_id(id)
		return node

	def create_responsible_party(self,data):

		"""
		Creates the responsible party in the system and returns the node_id
		"""
		# responsible = model.ResponsibleParty(data['name'],data['email'])
		# responsible.organization = data['organization']
		# responsible.phone = data['phone']
		# responsible.street = data['street']
		# responsible.state = data['state']
		# responsible.city = data['city']
		# responsible.zip = data['zip']
		
		data_dict = {'model':'ResponsibleParty'}
		data_dict['data']=data
		data_dict['process']='create'
		

		print "Data dict: ",data_dict		
		context = {'model': model}

		data_dict = get_action('additional_metadata')(context, data_dict)

		#responsible.save()
		return  data_dict

	def update_responsible_party(self,data):

		"""
		Creates the responsible party in the system and returns the node_id
		"""
		# responsible = model.ResponsibleParty(data['name'],data['email'])
		# responsible.organization = data['organization']
		# responsible.phone = data['phone']
		# responsible.street = data['street']
		# responsible.state = data['state']
		# responsible.city = data['city']
		# responsible.zip = data['zip']
		
		data_dict = {'model':'ResponsibleParty'}
		data_dict['data']=data
		data_dict['process']='update'
		

		print "Data dict: ",data_dict		
		context = {'model': model}

		data_dict = get_action('additional_metadata')(context, data_dict)

		#responsible.save()

		return  data_dict

	def do_harvest(self,data=None):
		
		print "Entering Harvest Node"
		data = clean_dict(unflatten(tuplize_dict(parse_params(
            request.params))))
			
		data_dict = {"id" : data['id']}
		context = {'model': model}
		try:
			get_action('do_harvest')(context, data_dict)
		except:
			h.flash_error("Error while harvesting", allow_html=True)

		url = h.url_for(controller='ckanext.ngds.ngdsui.controllers.contribute:ContributeController', action='index')
		redirect(url)

	def bulkupload_list(self):

		context = {'model': model, 'session': model.Session,'user': c.user or c.author}

		try:
			check_access('package_create',context,None)
		except NotAuthorized, error:
			err_str = _('User %s not authorized to access bulk uploads')% c.user
			#abort(401,error.__str__())	
			abort(401,err_str)
			

		uploads = model.BulkUpload.get_all()

		data = {'id':1}
		data_dict = {'model':'BulkUpload'}
		data_dict['data']=data
		data_dict['process']='read'
		context = {'model': model, 'session': model.Session}   
		#print get_action('transaction_data')(context,data_dict)

		#print model.BulkUpload.get(1)

		c.bulkuploads = uploads

		return render('contribute/bulkupload_list.html')

	def bulkupload_package_list(self):
		print "Entering Bulk upload package List"

		context = {'model': model, 'session': model.Session,'user': c.user or c.author}

		try:
			check_access('package_create',context,None)
		except NotAuthorized, error:
			err_str = _('User %s not authorized to access bulk uploads')% c.user
			#abort(401,error.__str__())	
			abort(401,err_str)	

		data = clean_dict(unflatten(tuplize_dict(parse_params(
            request.params))))

		uploaded_packages=model.BulkUpload_Package.by_bulk_upload(data['id'])

		print "uploaded_packages: ",uploaded_packages

		c.uploaded_packages = uploaded_packages
		c.selected_upload = model.BulkUpload.get(data['id'])

		return render('contribute/bulkupload_list.html')

	def execute_bulkupload(self):

		context = {'model': model, 'session': model.Session,'user': c.user or c.author}

		try:
			check_access('execute_bulkupload',context,None)
		except NotAuthorized, error:
			abort(401,error.__str__())	

		from ckanext.ngds.lib.importer.importer import BulkUploader

		bulkLoader = BulkUploader()
		bulkLoader.execute_bulk_upload()		

		h.flash_notice(_('Initiated Bulk Upload process and it is running in the background.'), allow_html=True)
		url = h.url_for(controller='ckanext.ngds.ngdsui.controllers.contribute:ContributeController', action='bulkupload_list')
		redirect(url)