# -*- coding: utf-8 -*- #
# Copyright 2023 Google LLC. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Log utilities for storage insights dataset-configs commands."""

from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

from googlecloudsdk.core import log


def dataset_config_operation_started_and_status_log(
    verb, dataset_config_name, operation_id
):
  # TODO: b/425284402 - change command to gcloud storage insights once GA.
  log.status.Print(
      '{} operation for dataset config {} has been successfully started.\nTo'
      ' check the status of this operation run: gcloud alpha storage insights'
      ' operations describe {}'.format(verb, dataset_config_name, operation_id)
  )
