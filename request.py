#!/usr/bin/env python
# coding:utf-8

"""
This module documents most elements of a processing request.
"""

# -- standard library --------------------------------------------------------
from datetime import datetime
from socket import getfqdn
import logging
import os

# -- project-specific --------------------------------------------------------
from .annotations_dispatcher import submit_annotations
from .service_exceptions import MissingArgumentError
from . import RemoteAccess

# -- Configuration ------------------------------------------------------------
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
THIS_DIR = os.path.dirname(__file__)


class Request(object):
    """
    Container class for all attributes relative to an annotation request.
    An instance of this class is meant to exist only during the processing
    of a request. (Hence it's name).

    Also offers general helper functions in the context of the Vesta workgroup
    annotators. (Can be used elsewhere also).
    """
    body = None
    url = None
    document = None
    misc = None
    current_progress = None
    process_version = None
    ann_srv_url = None
    annotations = None

    def __init__(self, body, task_handler, required_args=None):
        """
        Constructor.

        :param body: Body of request message as defined by Vesta-workgroup.
        :param task_handler: Task instance of a Celery application.
        :param required_args: Required argments in 'misc', expressed as a dict
                              where the key is the name of the arg and the
                              value is a description of it's use.
        """
        self.body = body
        self.type = self.body['service']['type']
        self.logger = logging.getLogger(__name__)
        self.logger.info(u"Handling task")
        doc = self.body['service']['document']
        self.host = getfqdn()
        self.misc = self.body['service']['misc']

        if required_args:
            for required_arg in required_args.keys():
                if not self.misc or required_arg not in self.misc:
                    raise MissingArgumentError(
                        'No URL supplied for : {0}'.
                        format(required_args[required_arg]))

        self.url = doc['url']
        self.ann_srv_url = self.body['annotation_service']['url']

        self.document = RemoteAccess.download(doc)
        self.task_handler = task_handler
        self.start_time = datetime.now().strftime(DATETIME_FORMAT)

    def set_progress(self, progress):
        """
        Helper function to set the progress state in the Celery Task backend.

        :param progress: Progress value between 0 and 100.
        :type progress: int
        """
        self.logger.debug(u"Setting progress to value {0}".format(progress))
        if type(progress) != int:
            raise TypeError("Progress must be expressed as an int")
        if progress < 0 or 100 < progress:
            raise ValueError("Progress must be between 0 and 100")

        self.current_progress = progress
        if self.task_handler:
            meta = {'current': progress,
                    'total': 100,
                    'worker_id_version': self.process_version,
                    'start_time': self.start_time,
                    'host': self.host,
                    'type': self.type}
            self.task_handler.update_state(state='PROGRESS', meta=meta)
        else:
            self.logger.warning(u"Could not set progress at back-end")

    def store_annotations(self, annotations):
        """
        Store the annotations on an Annotation Storage Service (ASS) if the
        ASS's URL was specified in the request body and the annotation has a
        valid result (not Null).

        Creates a transitory state which is called STORING which can be used to
        debug a hanging call to the ASS.

        :param annotations: Actual annotations to send to the ASS.
        """
        self.annotations = annotations

        if self.task_handler:
            meta = {'worker_id_version': self.process_version,
                    'start_time': self.start_time,
                    'host': self.host,
                    'type': self.type}
            self.task_handler.update_state(state='STORING', meta=meta)
        else:
            self.logger.warning(u"Could not set custom state STORING at"
                                u" back-end")

        if not self.ann_srv_url:
            self.logger.warning(u"Not submitting annotations to a null URL")
            return

        if not self.annotations:
            self.logger.warning(u"Not submitting empty annotations")
            return

        submit_annotations(self.ann_srv_url,
                           self.annotations)

    def __del__(self):
        """
        Destructor method for cleanup purposes.
        """
        if self.document:
            self.logger.info(u"Destroying local document copy of «{0}» =>"
                             u" «{1}»".
                             format(self.document, self.document.local_path))
            RemoteAccess.cleanup(self.document)
