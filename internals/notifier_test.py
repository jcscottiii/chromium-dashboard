# Copyright 2020 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License")
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import testing_config  # Must be imported before the module under test.
from datetime import datetime

import flask
from unittest import mock
import werkzeug.exceptions  # Flask HTTP stuff.
from google.cloud import ndb  # type: ignore

from api import converters

from internals import approval_defs
from internals import core_enums
from internals import notifier
from internals import stage_helpers
from internals.user_models import (
    AppUser, BlinkComponent, FeatureOwner, UserPref)
from internals.core_models import FeatureEntry, MilestoneSet, Stage
from internals.review_models import Gate
import settings

test_app = flask.Flask(__name__,
  template_folder=settings.get_flask_template_path())

# Load testdata to be used across all of the CustomTestCases
TESTDATA = testing_config.Testdata(__file__)

class EmailFormattingTest(testing_config.CustomTestCase):

  def setUp(self):
    self.fe_1 = FeatureEntry(
        name='feature one', summary='sum',
        owner_emails=['feature_owner@example.com'],
        #ot_milestone_desktop_start=100,
        editor_emails=['feature_editor@example.com', 'owner_1@example.com'],
        cc_emails=['cc@example.com'], category=1,
        devrel_emails=['devrel1@gmail.com'],
        creator_email='creator1@gmail.com',
        updater_email='editor1@gmail.com',
        blink_components=['Blink'],
        ff_views=1, safari_views=1,
        web_dev_views=1, standard_maturity=1)
    self.fe_1.put()

    self.ot_stage = Stage(feature_id=self.fe_1.key.integer_id(),
        stage_type=150, milestones=MilestoneSet(desktop_first=100))
    self.ship_stage = Stage(feature_id=self.fe_1.key.integer_id(),
        stage_type=160, milestones=MilestoneSet())
    self.ot_stage.put()
    self.ship_stage.put()
    self.fe_1_stages = stage_helpers.get_feature_stages(
        self.fe_1.key.integer_id())

    self.component_1 = BlinkComponent(name='Blink')
    self.component_1.put()
    self.component_owner_1 = FeatureOwner(
        name='owner_1', email='owner_1@example.com',
        primary_blink_components=[self.component_1.key])
    self.component_owner_1.put()
    self.watcher_1 = FeatureOwner(
        name='watcher_1', email='watcher_1@example.com',
        watching_all_features=True)
    self.watcher_1.put()
    self.changes = [dict(prop_name='test_prop', new_val='test new value',
                    old_val='test old value')]
    self.fe_2 = FeatureEntry(
        name='feature two', summary='sum',
        owner_emails=['feature_owner@example.com'],
        editor_emails=['feature_editor@example.com', 'owner_1@example.com'],
        category=1,
        creator_email='creator2@example.com',
        updater_email='editor2@example.com',
        blink_components=['Blink'], feature_type=1, ff_views=1, safari_views=1,
        web_dev_views=1, standard_maturity=1)
    self.fe_2.put()

    self.fe_2_ship_stage = Stage(feature_id=self.fe_2.key.integer_id(),
        stage_type=260, milestones=MilestoneSet())
    self.fe_2_ship_stage.put()
    self.fe_2_stages = stage_helpers.get_feature_stages(self.fe_2.key.integer_id())
    # This feature will only be used for the template tests.
    # Hardcode the Feature Key ID so that the ID is deterministic in the
    # template tests.
    self.template_fe = FeatureEntry(
        id=123, name='feature template', summary='sum',
        owner_emails=['feature_owner@example.com'],
        editor_emails=['feature_editor@example.com', 'owner_1@example.com'],
        category=1, creator_email='creator_template@example.com',
        updater_email='editor_template@example.com',
        blink_components=['Blink'], feature_type=0)
    self.template_ship_stage = Stage(feature_id=123, stage_type=160,
        milestones=MilestoneSet(desktop_first=100))
    self.template_ship_stage_2 = Stage(feature_id=123, stage_type=160,
        milestones=MilestoneSet(desktop_first=103))
    self.template_fe.put()
    self.template_ship_stage.put()
    self.template_ship_stage_2.put()
    self.template_fe.key = ndb.Key('FeatureEntry', 123)
    self.template_fe.put()

    self.maxDiff = None

  def tearDown(self):
    kinds = [FeatureEntry, Stage, FeatureOwner, BlinkComponent, Gate]
    for kind in kinds:
      for entity in kind.query():
        entity.key.delete()

  def test_format_email_body__new(self):
    """We generate an email body for new features."""
    with test_app.app_context():
      body_html = notifier.format_email_body(
          'new-feature-email.html', self.template_fe, [])
    # TESTDATA.make_golden(body_html, 'test_format_email_body__new.html')
    self.assertEqual(body_html,
      TESTDATA['test_format_email_body__new.html'])

  def test_format_email_body__update_no_changes(self):
    """We don't crash if the change list is emtpy."""
    with test_app.app_context():
      body_html = notifier.format_email_body(
          'update-feature-email.html', self.template_fe, [])
    # TESTDATA.make_golden(body_html, 'test_format_email_body__update_no_changes.html')
    self.assertEqual(body_html,
      TESTDATA['test_format_email_body__update_no_changes.html'])

  def test_format_email_body__update_with_changes(self):
    """We generate an email body for an updated feature."""
    with test_app.app_context():
      body_html = notifier.format_email_body(
          'update-feature-email.html', self.template_fe, self.changes)
    # TESTDATA.make_golden(body_html, 'test_format_email_body__update_with_changes.html')
    self.assertEqual(body_html,
      TESTDATA['test_format_email_body__update_with_changes.html'])

  def test_format_email_body__mozdev_links(self):
    """We generate an email body with links to developer.mozilla.org."""
    self.fe_1.doc_links = ['https://developer.mozilla.org/look-here']
    with test_app.app_context():
      body_html = notifier.format_email_body(
          'update-feature-email.html', self.template_fe, self.changes)
    # TESTDATA.make_golden(body_html, 'test_format_email_body__mozdev_links_mozilla.html')
    self.assertEqual(body_html,
      TESTDATA['test_format_email_body__mozdev_links_mozilla.html'])

    self.fe_1.doc_links = [
        'https://hacker-site.org/developer.mozilla.org/look-here']
    with test_app.app_context():
      body_html = notifier.format_email_body(
          'update-feature-email.html', self.template_fe, self.changes)
    # TESTDATA.make_golden(body_html, 'test_format_email_body__mozdev_links_non_mozilla.html')
    self.assertEqual(body_html,
      TESTDATA['test_format_email_body__mozdev_links_non_mozilla.html'])

  def test_accumulate_reasons(self):
    """We can accumulate lists of reasons why we sent a message to a user."""
    addr_reasons = collections.defaultdict(list)

    # Adding an empty list of users
    notifier.accumulate_reasons(addr_reasons, [], 'a reason')
    self.assertEqual({}, addr_reasons)

    # Adding some users builds up a bigger reason dictionary.
    notifier.accumulate_reasons(
        addr_reasons, [self.component_owner_1.email], 'a reason')
    self.assertEqual(
        {'owner_1@example.com': ['a reason']},
        addr_reasons)

    notifier.accumulate_reasons(
        addr_reasons, [self.component_owner_1.email, self.watcher_1.email],
        'another reason')
    self.assertEqual(
        {'owner_1@example.com': ['a reason', 'another reason'],
         'watcher_1@example.com': ['another reason'],
        },
        addr_reasons)

    # We can also add email addresses that are not users.
    notifier.accumulate_reasons(
        addr_reasons, ['mailing-list@example.com'], 'third reason')
    self.assertEqual(
        {'owner_1@example.com': ['a reason', 'another reason'],
         'watcher_1@example.com': ['another reason'],
         'mailing-list@example.com': ['third reason'],
        },
        addr_reasons)

  def test_convert_reasons_to_task__no_reasons(self):
    with self.assertRaises(AssertionError):
      notifier.convert_reasons_to_task(
          'addr', [], 'html', 'subject', 'triggerer')

  def test_convert_reasons_to_task__normal(self):
    actual = notifier.convert_reasons_to_task(
        'addr', ['reason 1', 'reason 2'], 'html', 'subject',
        'triggerer@example.com')
    self.assertCountEqual(
        ['to', 'subject', 'html', 'reply_to'],
        list(actual.keys()))
    self.assertEqual('addr', actual['to'])
    self.assertEqual('subject', actual['subject'])
    self.assertEqual(None, actual['reply_to'])  # Lacks perm to reply.
    self.assertIn('html', actual['html'])
    self.assertIn('reason 1', actual['html'])
    self.assertIn('reason 2', actual['html'])

  def test_convert_reasons_to_task__can_reply(self):
    """If the user is allowed to reply, set reply_to to the triggerer."""
    actual = notifier.convert_reasons_to_task(
        'user@chromium.org', ['reason 1', 'reason 2'], 'html', 'subject',
        'triggerer@example.com')
    self.assertCountEqual(
        ['to', 'subject', 'html', 'reply_to'],
        list(actual.keys()))
    self.assertEqual('user@chromium.org', actual['to'])
    self.assertEqual('subject', actual['subject'])
    self.assertEqual('triggerer@example.com', actual['reply_to'])

  def test_apply_subscription_rules__iwa_match(self):
    """When a feature has category IWA rule, a reason is returned."""
    self.fe_1.category = core_enums.IWA
    changes = [{'prop_name': 'shipped_android_milestone'}]  # Anything

    actual = notifier.apply_subscription_rules(
        self.fe_1, changes)

    self.assertEqual(
        {notifier.IWA_RULE_REASON: notifier.IWA_RULE_ADDRS},
        actual)

  def test_apply_subscription_rules__relevant_match(self):
    """When a feature and change match a rule, a reason is returned."""
    self.ship_stage.milestones.android_first = 88
    changes = [{'prop_name': 'shipped_android_milestone'}]

    actual = notifier.apply_subscription_rules(
        self.fe_1, changes)

    self.assertEqual(
        {notifier.WEBVIEW_RULE_REASON: notifier.WEBVIEW_RULE_ADDRS},
        actual)

  def test_apply_subscription_rules__irrelevant_match(self):
    """When a feature matches, but the change is not relevant => skip."""
    self.ship_stage.milestones.android_first = 88
    self.ship_stage.put()
    changes = [{'prop_name': 'some_other_field'}]  # irrelevant changesa

    actual = notifier.apply_subscription_rules(
        self.fe_1, changes)

    self.assertEqual({}, actual)

  def test_apply_subscription_rules__non_match(self):
    """When a feature is not a match => skip."""
    changes = [{'prop_name': 'shipped_android_milestone'}]

    # No milestones of any kind set.
    actual = notifier.apply_subscription_rules(
        self.fe_1, changes)
    self.assertEqual({}, actual)

    # Webview is also set
    self.ship_stage.milestones.android_first = 88
    self.ship_stage.milestones.webview_first = 89
    actual = notifier.apply_subscription_rules(
        self.fe_1, changes)
    self.assertEqual({}, actual)

  @mock.patch('internals.notifier.format_email_body')
  def test_make_feature_changes_email__new(self, mock_f_e_b):
    """We send email to component owners and subscribers for new features."""
    mock_f_e_b.return_value = 'mock body html'
    actual_tasks = notifier.make_feature_changes_email(
        self.fe_1, is_update=False, changes=[])
    self.assertEqual(6, len(actual_tasks))
    (feature_cc_task, devrel_task, feature_editor_task, feature_owner_task,
     component_owner_task, watcher_task) = actual_tasks

    # Notification to feature owner.
    self.assertEqual('feature_owner@example.com', feature_owner_task['to'])
    self.assertEqual('new feature: feature one', feature_owner_task['subject'])
    self.assertIn('mock body html', feature_owner_task['html'])
    self.assertIn('<li>You are listed as an owner of this feature</li>',
      feature_owner_task['html'])

    # Notification to feature editor.
    self.assertEqual('new feature: feature one', feature_editor_task['subject'])
    self.assertIn('mock body html', feature_editor_task['html'])
    self.assertIn('<li>You are listed as an editor of this feature</li>',
      feature_editor_task['html'])
    self.assertEqual('feature_editor@example.com', feature_editor_task['to'])

    # Notification to devrel to feature changes.
    self.assertEqual('new feature: feature one', devrel_task['subject'])
    self.assertIn('mock body html', devrel_task['html'])
    self.assertIn('<li>You are a devrel contact for this feature.</li>',
      devrel_task['html'])
    self.assertEqual('devrel1@gmail.com', devrel_task['to'])

    # Notification to user CC'd to feature changes.
    self.assertEqual('new feature: feature one', feature_cc_task['subject'])
    self.assertIn('mock body html', feature_cc_task['html'])
    self.assertIn('<li>You are CC\'d on this feature</li>',
      feature_cc_task['html'])
    self.assertEqual('cc@example.com', feature_cc_task['to'])

    # Notification to component owner.
    self.assertEqual('new feature: feature one', component_owner_task['subject'])
    self.assertIn('mock body html', component_owner_task['html'])
    # Component owner is also a feature editor and should have both reasons.
    self.assertIn('<li>You are an owner of this feature\'s component</li>\n'
                  '<li>You are listed as an editor of this feature</li>',
      component_owner_task['html'])
    self.assertEqual('owner_1@example.com', component_owner_task['to'])

    # Notification to feature change watcher.
    self.assertEqual('new feature: feature one', watcher_task['subject'])
    self.assertIn('mock body html', watcher_task['html'])
    self.assertIn('<li>You are watching all feature changes</li>',
      watcher_task['html'])
    self.assertEqual('watcher_1@example.com', watcher_task['to'])

    mock_f_e_b.assert_called_once_with(
        'new-feature-email.html', self.fe_1, [])

  @mock.patch('internals.notifier.format_email_body')
  def test_make_feature_changes_email__update(self, mock_f_e_b):
    """We send email to component owners and subscribers for edits."""
    mock_f_e_b.return_value = 'mock body html'
    actual_tasks = notifier.make_feature_changes_email(
        self.fe_1, True, self.changes)
    self.assertEqual(6, len(actual_tasks))
    (feature_cc_task, devrel_task, feature_editor_task, feature_owner_task,
     component_owner_task, watcher_task) = actual_tasks

    # Notification to feature owner.
    self.assertEqual('feature_owner@example.com', feature_owner_task['to'])
    self.assertEqual('updated feature: feature one',
      feature_owner_task['subject'])
    self.assertIn('mock body html', feature_owner_task['html'])
    self.assertIn('<li>You are listed as an owner of this feature</li>',
      feature_owner_task['html'])

    # Notification to feature editor.
    self.assertEqual('updated feature: feature one',
      feature_editor_task['subject'])
    self.assertIn('mock body html', feature_editor_task['html'])
    self.assertIn('<li>You are listed as an editor of this feature</li>',
      feature_editor_task['html'])
    self.assertEqual('feature_editor@example.com', feature_editor_task['to'])

    # Notification to devrel to feature changes.
    self.assertEqual('updated feature: feature one', devrel_task['subject'])
    self.assertIn('mock body html', devrel_task['html'])
    self.assertIn('<li>You are a devrel contact for this feature.</li>',
      devrel_task['html'])
    self.assertEqual('devrel1@gmail.com', devrel_task['to'])

    # Notification to user CC'd on feature changes.
    self.assertEqual('updated feature: feature one',
      feature_cc_task['subject'])
    self.assertIn('mock body html', feature_cc_task['html'])
    self.assertIn('<li>You are CC\'d on this feature</li>',
      feature_cc_task['html'])
    self.assertEqual('cc@example.com', feature_cc_task['to'])

    # Notification to component owner.
    self.assertEqual('updated feature: feature one',
      component_owner_task['subject'])
    self.assertIn('mock body html', component_owner_task['html'])
    # Component owner is also a feature editor and should have both reasons.
    self.assertIn('<li>You are an owner of this feature\'s component</li>\n'
                  '<li>You are listed as an editor of this feature</li>',
      component_owner_task['html'])
    self.assertEqual('owner_1@example.com', component_owner_task['to'])

    # Notification to feature change watcher.
    self.assertEqual('updated feature: feature one', watcher_task['subject'])
    self.assertIn('mock body html', watcher_task['html'])
    self.assertIn('<li>You are watching all feature changes</li>',
      watcher_task['html'])
    self.assertEqual('watcher_1@example.com', watcher_task['to'])

    mock_f_e_b.assert_called_once_with(
        'update-feature-email.html', self.fe_1, self.changes)

  @mock.patch('internals.notifier.format_email_body')
  @mock.patch('internals.approval_defs.get_approvers')
  def test_make_review_requests_email__unassigned(
      self, mock_get_approvers, mock_f_e_b):
    """We send email to approvers for a review request."""
    mock_f_e_b.return_value = 'mock body html'
    mock_get_approvers.return_value = ['approver1@example.com', 'approver2@example.com']

    actual_tasks = notifier.make_review_requests_email(
        self.fe_1, 1, self.changes)
    self.assertEqual(2, len(actual_tasks))
    review_task_1 = actual_tasks[0]

    # Notification to feature change watcher.
    self.assertEqual('Review Request for feature: feature one', review_task_1['subject'])
    self.assertIn('mock body html', review_task_1['html'])
    self.assertIn('<li>You are a reviewer for this type of gate</li>',
      review_task_1['html'])
    self.assertEqual('approver1@example.com', review_task_1['to'])

    review_task_2 = actual_tasks[1]

    # Notification to feature change watcher.
    self.assertEqual('Review Request for feature: feature one', review_task_2['subject'])
    self.assertIn('mock body html', review_task_2['html'])
    self.assertIn('<li>You are a reviewer for this type of gate</li>',
      review_task_2['html'])
    self.assertEqual('approver2@example.com', review_task_2['to'])

    mock_f_e_b.assert_called_once_with(
        'update-feature-email.html', self.fe_1, self.changes)
    mock_get_approvers.assert_called_once_with(1)

  @mock.patch('internals.notifier.format_email_body')
  def test_make_review_requests_email__assigned(self, mock_f_e_b):
    """We send email to the assigned reviewer for a review request."""
    mock_f_e_b.return_value = 'mock body html'
    gate_1 = Gate(
        feature_id=self.fe_1.key.integer_id(), gate_type=1,
        stage_id=123, state=0, assignee_emails=['approver3@example.com'])
    gate_1.put()

    actual_tasks = notifier.make_review_requests_email(
        self.fe_1, 1, self.changes)
    self.assertEqual(1, len(actual_tasks))
    review_task_1 = actual_tasks[0]

    # Notification to feature change watcher.
    self.assertEqual('Review Request for feature: feature one', review_task_1['subject'])
    self.assertIn('mock body html', review_task_1['html'])
    self.assertIn('<li>This review is assigned to you</li>',
      review_task_1['html'])
    self.assertEqual('approver3@example.com', review_task_1['to'])

  @mock.patch('internals.notifier.format_email_body')
  @mock.patch('internals.approval_defs.get_approvers')
  def test_make_new_comments_email__unassigned(
      self, mock_get_approvers, mock_f_e_b):
    """We send email to approvers for a review request."""
    mock_f_e_b.return_value = 'mock body html'
    mock_get_approvers.return_value = ['approver1@example.com']

    actual_tasks = notifier.make_new_comments_email(
        self.fe_1, 1, self.changes)
    self.assertEqual(6, len(actual_tasks))
    (review_task_1, feature_cc_task, devrel_task,
     feature_editor_task, feature_owner_task, feature_editor_task_2) = actual_tasks

    self.assertEqual('New comments for feature: feature one', review_task_1['subject'])
    self.assertIn('mock body html', review_task_1['html'])
    self.assertIn('<li>You are a reviewer for this type of gate</li>',
      review_task_1['html'])
    self.assertEqual('approver1@example.com', review_task_1['to'])

    # Notification to feature owner.
    self.assertEqual('feature_owner@example.com', feature_owner_task['to'])
    self.assertEqual('New comments for feature: feature one',
      feature_owner_task['subject'])
    self.assertIn('mock body html', feature_owner_task['html'])
    self.assertIn('<li>You are listed as an owner of this feature</li>',
      feature_owner_task['html'])

    # Notification to feature editor.
    self.assertEqual('New comments for feature: feature one',
      feature_editor_task['subject'])
    self.assertIn('mock body html', feature_editor_task['html'])
    self.assertIn('<li>You are listed as an editor of this feature</li>',
      feature_editor_task['html'])
    self.assertEqual('feature_editor@example.com', feature_editor_task['to'])

    # Notification to devrel to feature changes.
    self.assertEqual('New comments for feature: feature one', devrel_task['subject'])
    self.assertIn('mock body html', devrel_task['html'])
    self.assertIn('<li>You are a devrel contact for this feature.</li>',
      devrel_task['html'])
    self.assertEqual('devrel1@gmail.com', devrel_task['to'])

    # Notification to user CC'd on feature changes.
    self.assertEqual('New comments for feature: feature one',
      feature_cc_task['subject'])
    self.assertIn('mock body html', feature_cc_task['html'])
    self.assertIn('<li>You are CC\'d on this feature</li>',
      feature_cc_task['html'])
    self.assertEqual('cc@example.com', feature_cc_task['to'])

    self.assertEqual('New comments for feature: feature one', feature_editor_task_2['subject'])
    self.assertIn('mock body html', feature_editor_task_2['html'])
    self.assertIn('<li>You are listed as an editor of this feature</li>',
      feature_editor_task_2['html'])
    self.assertEqual('owner_1@example.com', feature_editor_task_2['to'])

    mock_f_e_b.assert_called_once_with(
        'update-feature-email.html', self.fe_1, self.changes)
    mock_get_approvers.assert_called_once_with(1)

  @mock.patch('internals.notifier.format_email_body')
  def test_make_new_comments_email__assigned(self, mock_f_e_b):
    """We send email to approvers for a review request."""
    mock_f_e_b.return_value = 'mock body html'
    gate_1 = Gate(
        feature_id=self.fe_1.key.integer_id(), gate_type=1,
        stage_id=123, state=0, assignee_emails=['approver3@example.com'])
    gate_1.put()

    actual_tasks = notifier.make_new_comments_email(
        self.fe_1, 1, self.changes)
    self.assertEqual(6, len(actual_tasks))
    review_task_1 = actual_tasks[0]

    self.assertEqual('New comments for feature: feature one', review_task_1['subject'])
    self.assertIn('mock body html', review_task_1['html'])
    self.assertIn('<li>This review is assigned to you</li>',
      review_task_1['html'])
    self.assertEqual('approver3@example.com', review_task_1['to'])

  @mock.patch('internals.notifier.format_email_body')
  def test_make_feature_changes_email__starrer(self, mock_f_e_b):
    """We send email to users who starred the feature."""
    mock_f_e_b.return_value = 'mock body html'
    notifier.FeatureStar.set_star(
        'starrer_1@example.com', self.fe_1.key.integer_id())
    actual_tasks = notifier.make_feature_changes_email(
        self.fe_1, True, self.changes)
    self.assertEqual(7, len(actual_tasks))
    (feature_cc_task, devrel_task, feature_editor_task, feature_owner_task,
     component_owner_task, starrer_task, watcher_task) = actual_tasks

    # Notification to feature owner.
    self.assertEqual('feature_owner@example.com', feature_owner_task['to'])
    self.assertEqual('updated feature: feature one',
      feature_owner_task['subject'])
    self.assertIn('mock body html', feature_owner_task['html'])
    self.assertIn('<li>You are listed as an owner of this feature</li>',
      feature_owner_task['html'])

    # Notification to feature editor.
    self.assertEqual('updated feature: feature one',
      feature_editor_task['subject'])
    self.assertIn('mock body html', feature_editor_task['html'])
    self.assertIn('<li>You are listed as an editor of this feature</li>',
      feature_editor_task['html'])
    self.assertEqual('feature_editor@example.com', feature_editor_task['to'])

    # Notification to devrel to feature changes.
    self.assertEqual('updated feature: feature one', devrel_task['subject'])
    self.assertIn('mock body html', devrel_task['html'])
    self.assertIn('<li>You are a devrel contact for this feature.</li>',
      devrel_task['html'])
    self.assertEqual('devrel1@gmail.com', devrel_task['to'])

    # Notification to user CC'd on feature changes.
    self.assertEqual('updated feature: feature one',
      feature_cc_task['subject'])
    self.assertIn('mock body html', feature_cc_task['html'])
    self.assertIn('<li>You are CC\'d on this feature</li>',
      feature_cc_task['html'])
    self.assertEqual('cc@example.com', feature_cc_task['to'])

    # Notification to component owner.
    self.assertEqual('updated feature: feature one',
      component_owner_task['subject'])
    self.assertIn('mock body html', component_owner_task['html'])
    # Component owner is also a feature editor and should have both reasons.
    self.assertIn('<li>You are an owner of this feature\'s component</li>\n'
                  '<li>You are listed as an editor of this feature</li>',
      component_owner_task['html'])
    self.assertEqual('owner_1@example.com', component_owner_task['to'])

    # Notification to feature starrer.
    self.assertEqual('updated feature: feature one', starrer_task['subject'])
    self.assertIn('mock body html', starrer_task['html'])
    self.assertIn('<li>You starred this feature</li>',
      starrer_task['html'])
    self.assertEqual('starrer_1@example.com', starrer_task['to'])

    # Notification to feature change watcher.
    self.assertEqual('updated feature: feature one', watcher_task['subject'])
    self.assertIn('mock body html', watcher_task['html'])
    self.assertIn('<li>You are watching all feature changes</li>',
      watcher_task['html'])
    self.assertEqual('watcher_1@example.com', watcher_task['to'])

    mock_f_e_b.assert_called_once_with(
        'update-feature-email.html', self.fe_1, self.changes)


  @mock.patch('internals.notifier.format_email_body')
  def test_make_feature_changes_email__starrer_unsubscribed(self, mock_f_e_b):
    """We don't email users who starred the feature but opted out."""
    mock_f_e_b.return_value = 'mock body html'
    starrer_2_pref = UserPref(
        email='starrer_2@example.com',
        notify_as_starrer=False)
    starrer_2_pref.put()
    notifier.FeatureStar.set_star(
        'starrer_2@example.com', self.fe_2.key.integer_id())
    actual_tasks = notifier.make_feature_changes_email(
        self.fe_2, True, self.changes)
    self.assertEqual(4, len(actual_tasks))
    # Note: There is no starrer_task.
    (feature_editor_task, feature_owner_task, component_owner_task,
     watcher_task) = actual_tasks
    self.assertEqual('feature_editor@example.com', feature_editor_task['to'])
    self.assertEqual('feature_owner@example.com', feature_owner_task['to'])
    self.assertEqual('owner_1@example.com', component_owner_task['to'])
    self.assertEqual('watcher_1@example.com', watcher_task['to'])
    mock_f_e_b.assert_called_once_with(
        'update-feature-email.html', self.fe_2, self.changes)


class FeatureStarTest(testing_config.CustomTestCase):

  def setUp(self):
    self.fe_1 = FeatureEntry(
        name='feature one', summary='sum', category=1)
    self.fe_1.put()
    self.fe_2 = FeatureEntry(
        name='feature two', summary='sum', category=1)
    self.fe_2.put()
    self.fe_3 = FeatureEntry(
        name='feature three', summary='sum', category=1)
    self.fe_3.put()

  def tearDown(self):
    self.fe_1.key.delete()
    self.fe_2.key.delete()
    self.fe_3.key.delete()

  def test_get_star__no_existing(self):
    """User has never starred the given feature."""
    email = 'user1@example.com'
    feature_id = self.fe_1.key.integer_id()
    actual = notifier.FeatureStar.get_star(email, feature_id)
    self.assertEqual(None, actual)

  def test_get_and_set_star(self):
    """User can star and unstar a feature."""
    email = 'user2@example.com'
    feature_id = self.fe_1.key.integer_id()
    notifier.FeatureStar.set_star(email, feature_id)
    actual = notifier.FeatureStar.get_star(email, feature_id)
    self.assertEqual(email, actual.email)
    self.assertEqual(feature_id, actual.feature_id)
    self.assertTrue(actual.starred)
    updated_fe = FeatureEntry.get_by_id(feature_id)
    self.assertEqual(1, updated_fe.star_count)

    notifier.FeatureStar.set_star(email, feature_id, starred=False)
    actual = notifier.FeatureStar.get_star(email, feature_id)
    self.assertEqual(email, actual.email)
    self.assertEqual(feature_id, actual.feature_id)
    self.assertFalse(actual.starred)
    updated_fe = FeatureEntry.get_by_id(feature_id)
    self.assertEqual(0, updated_fe.star_count)

  def test_get_user_stars__no_stars(self):
    """User has never starred any features."""
    email = 'user4@example.com'
    with test_app.app_context():
      actual = notifier.FeatureStar.get_user_stars(email)
    self.assertEqual([], actual)

  def test_get_user_stars__some_stars(self):
    """User has starred three features."""
    email = 'user5@example.com'
    feature_1_id = self.fe_1.key.integer_id()
    feature_2_id = self.fe_2.key.integer_id()
    feature_3_id = self.fe_3.key.integer_id()
    # Note intermixed order
    notifier.FeatureStar.set_star(email, feature_1_id)
    notifier.FeatureStar.set_star(email, feature_3_id)
    notifier.FeatureStar.set_star(email, feature_2_id)

    actual = notifier.FeatureStar.get_user_stars(email)
    expected_ids = [feature_1_id, feature_2_id, feature_3_id]
    self.assertEqual(sorted(expected_ids, reverse=True), actual)
    # Cleanup
    for feature_id in expected_ids:
      notifier.FeatureStar.get_star(email, feature_id).key.delete()

  def test_get_feature_starrers__no_stars(self):
    """No user has starred the given feature."""
    feature_1_id = self.fe_1.key.integer_id()
    actual = notifier.FeatureStar.get_feature_starrers(feature_1_id)
    self.assertEqual([], actual)

  def test_get_feature_starrers__some_starrers(self):
    """Two users have starred the given feature."""
    app_user_1 = AppUser(email='user16@example.com')
    app_user_1.put()
    app_user_2 = AppUser(email='user17@example.com')
    app_user_2.put()
    feature_1_id = self.fe_1.key.integer_id()
    notifier.FeatureStar.set_star(app_user_1.email, feature_1_id)
    notifier.FeatureStar.set_star(app_user_2.email, feature_1_id)


    user_1_email = app_user_1.email
    user_2_email = app_user_2.email
    app_user_1.key.delete()
    app_user_2.key.delete()
    actual = notifier.FeatureStar.get_feature_starrers(feature_1_id)
    self.assertCountEqual(
        [user_1_email, user_2_email],
        [au.email for au in actual])


class NotifyInactiveUsersHandlerTest(testing_config.CustomTestCase):

  def setUp(self):
    active_user = AppUser(
      created=datetime(2020, 10, 1),
      email="active_user@example.com", is_admin=False, is_site_editor=False,
      last_visit=datetime(2023, 8, 30))
    active_user.put()

    inactive_user = AppUser(
      created=datetime(2020, 10, 1),
      email="inactive_user@example.com", is_admin=False, is_site_editor=False,
      last_visit=datetime(2023, 2, 20))
    inactive_user.put()
    self.inactive_user = inactive_user

    # User who has recently been given access by an admin,
    # but has not yet visited the site. They should not be considered inactive.
    newly_created_user = AppUser(
      created=datetime(2023, 8, 1),
      email="new_user@example.com", is_admin=False, is_site_editor=False)
    newly_created_user.put()

    # Very inactive user who has already been warned of inactivity
    # via notification. They should not receive a second notification.
    really_inactive_user = AppUser(
      created=datetime(2020, 10, 1),
      email="really_inactive_user@example.com", is_admin=False,
      is_site_editor=False, last_visit=datetime(2022, 10, 1),
      notified_inactive=True)
    really_inactive_user.put()

    active_admin = AppUser(
      created=datetime(2020, 10, 1),
      email="active_admin@example.com", is_admin=True, is_site_editor=True,
      last_visit=datetime(2023, 9, 30))
    active_admin.put()

    inactive_admin = AppUser(
      created=datetime(2020, 10, 1),
      email="inactive_admin@example.com", is_admin=True, is_site_editor=True,
      last_visit=datetime(2023, 3, 1))
    inactive_admin.put()

    active_site_editor = AppUser(
      created=datetime(2020, 10, 1),
      email="active_site_editor@example.com", is_admin=False,
      is_site_editor=True, last_visit=datetime(2023, 7, 30))
    active_site_editor.put()

    inactive_site_editor = AppUser(
      created=datetime(2020, 10, 1),
      email="inactive_site_editor@example.com", is_admin=False,
      is_site_editor=True, last_visit=datetime(2023, 2, 9))
    inactive_site_editor.put()

  def tearDown(self):
    for user in AppUser.query():
      user.key.delete()

  def test_determine_users_to_notify(self):
    with test_app.app_context():
      inactive_notifier = notifier.NotifyInactiveUsersHandler()
      result = inactive_notifier.get_template_data(now=datetime(2023, 9, 1))
    expected = ('1 users notified of inactivity.\n'
        'Notified users:\ninactive_user@example.com')
    self.assertEqual(result.get('message', None), expected)
    # The inactive user who was notified should be flagged as notified.
    self.assertTrue(self.inactive_user.notified_inactive)


class OriginTrialCreationRequestHandlerTest(testing_config.CustomTestCase):
  def setUp(self):
    self.feature = FeatureEntry(
        id=1, name='A feature', summary='summary', category=1)
    self.ot_stage = Stage(
      feature_id=1,
      stage_type=150,
      intent_thread_url='https://example.com/intent',
      ot_chromium_trial_name='ChromiumTrialName',
      ot_description='A brief description.',
      ot_display_name='A new origin trial',
      ot_documentation_url='https://example.com/docs',
      ot_feedback_submission_url='https://example.com/feedback',
      ot_has_third_party_support=True,
      ot_is_deprecation_trial=True,
      ot_is_critical_trial=False,
      ot_owner_email='owner@example.com',
      ot_emails=['user1@example.com', 'user2@example.com'],
      ot_webfeature_use_counter='kWebFeature',
      ot_request_note='Additional information about the trial creation.',
      milestones=MilestoneSet(
        desktop_first=100,
        desktop_last=200,
      ),
    )
    self.feature.put()
    self.ot_stage.put()

  def tearDown(self) -> None:
    kinds: list[ndb.Model] = [FeatureEntry, Stage]
    for kind in kinds:
      for entity in kind.query():
        entity.key.delete()

  def test_make_creation_request_email(self):
    stage_dict = converters.stage_to_json_dict(self.ot_stage)
    stage_dict['ot_request_note'] = self.ot_stage.ot_request_note
    handler = notifier.OriginTrialCreationRequestHandler()
    email_task = handler.make_creation_request_email(stage_dict)

    expected_body = """
<p>
  Requested by: owner@example.com
  <br>
  Additional contacts for your team?: user1@example.com,user2@example.com
  <br>
  Feature name: A new origin trial
  <br>
  Feature description: A brief description.
  <br>
  Start Chrome milestone: 100
  <br>
  End Chrome milestone: 200
  <br>
  Chromium trial name: ChromiumTrialName
  <br>
  Is this a deprecation trial?: Yes
  <br>
  Third party origin support: Yes
  <br>
  WebFeature UseCounter value: kWebFeature
  <br>
  Documentation link: https://example.com/docs
  <br>
  Chromestatus link: https://chromestatus.com/feature/1
  <br>
  Feature feedback link: https://example.com/feedback
  <br>
  Intent to Experiment link: https://example.com/intent
  <br>
  Is this a critical trial?: No
  <br>
  Anything else?: Additional information about the trial creation.
  <br>
  <br>
  Instructions for handling this request can be found at: https://g3doc.corp.google.com/chrome/origin_trials/g3doc/trial_admin.md?cl=head#setup-a-new-trial
</p>
"""
    expected = {
      'to': 'origin-trials-support@google.com',
      'subject': f'New Trial Creation Request for A new origin trial',
      'reply_to': None,
      'html': expected_body,
    }

    self.assertEqual(email_task, expected)


class OriginTrialExtensionRequestHandlerTest(testing_config.CustomTestCase):
  def setUp(self):
    self.feature = FeatureEntry(
        id=1, name='A feature', summary='summary', category=1)
    self.ot_stage = Stage(
      id=10,
      feature_id=1,
      stage_type=150,
      intent_thread_url='https://example.com/intent',
      ot_chromium_trial_name='ChromiumTrialName',
      ot_description='A brief description.',
      ot_display_name='A new origin trial',
      ot_documentation_url='https://example.com/docs',
      ot_feedback_submission_url='https://example.com/feedback',
      ot_has_third_party_support=True,
      ot_is_deprecation_trial=True,
      ot_is_critical_trial=False,
      ot_owner_email='owner@example.com',
      ot_emails=['user1@example.com', 'user2@example.com'],
      ot_webfeature_use_counter='kWebFeature',
      ot_request_note='Additional information about the trial creation.',
      milestones=MilestoneSet(
        desktop_first=100,
        desktop_last=200,
      ),
    )
    self.extension_stage = Stage(
      feature_id=1,
      ot_stage_id=10,
      stage_type=151,
      ot_owner_email='another_user@example.com',
      intent_thread_url='https://example.com/extension',
      milestones=MilestoneSet(desktop_last=203),
      ot_request_note='Some more information about the trial extension.',
    )
    self.feature.put()
    self.ot_stage.put()
    self.extension_stage.put()

  def tearDown(self) -> None:
    kinds: list[ndb.Model] = [FeatureEntry, Stage]
    for kind in kinds:
      for entity in kind.query():
        entity.key.delete()

  def test_make_extension_request_email(self):
    ot_stage_dict = converters.stage_to_json_dict(self.ot_stage)
    extenson_stage_dict = converters.stage_to_json_dict(self.extension_stage)
    extenson_stage_dict['ot_request_note'] = (
        self.extension_stage.ot_request_note)
    handler = notifier.OriginTrialExtensionRequestHandler()
    email_task = handler.make_extension_request_email(
        extenson_stage_dict, ot_stage_dict)

    expected_body = f"""
<p>
  Requested by: another_user@example.com
  <br>
  Feature name: A new origin trial
  <br>
  Intent to Extend Experiment URL: https://example.com/extension
  <br>
  New end milestone: 203
  <br>
  Anything else?: Some more information about the trial extension.
  <br>
  <br>
  Instructions for handling this request can be found at: https://g3doc.corp.google.com/chrome/origin_trials/g3doc/trial_admin.md#extend-an-existing-trial
</p>
"""

    expected = {
      'to': 'origin-trials-support@google.com',
      'subject': f'New Trial Extension Request for A new origin trial',
      'reply_to': None,
      'html': expected_body,
    }

    self.assertEqual(email_task, expected)


class FunctionsTest(testing_config.CustomTestCase):

  def setUp(self):
    quoted_msg_id = 'xxx%3Dyyy%40mail.gmail.com'
    impl_url = notifier.BLINK_DEV_ARCHIVE_URL_PREFIX + '123' + quoted_msg_id
    expr_url = notifier.TEST_ARCHIVE_URL_PREFIX + '456' + quoted_msg_id
    self.fe_1 = FeatureEntry(
        name='feature one', summary='sum', category=1, feature_type=0)
    self.fe_1.put()

    stages = []
    # Prototyping stage.
    self.proto_stage = Stage(feature_id=self.fe_1.key.integer_id(),
        stage_type=120, intent_thread_url=impl_url)
    stages.append(self.proto_stage)
    # Origin trial stage.
    self.ot_stage = Stage(feature_id=self.fe_1.key.integer_id(), stage_type=150,
        intent_thread_url=expr_url)
    stages.append(self.ot_stage)
    # Ship stage with no intent thread url.
    self.ship_stage = Stage(
        feature_id=self.fe_1.key.integer_id(), stage_type=160,
        intent_thread_url=None)
    stages.append(self.ship_stage)
    ndb.put_multi(stages)

  def tearDown(self) -> None:
    kinds: list[ndb.Model] = [FeatureEntry, Stage]
    for kind in kinds:
      for entity in kind.query():
        entity.key.delete()

  def test_get_thread_id__normal(self):
    """We can select the correct approval thread field of a feature."""
    self.assertEqual(
        '123xxx=yyy@mail.gmail.com',
        notifier.get_thread_id(self.proto_stage))
    self.assertEqual(
        '456xxx=yyy@mail.gmail.com',
        notifier.get_thread_id(self.ot_stage))
    self.assertEqual(
        None,
        notifier.get_thread_id(self.ship_stage))

  def test_generate_thread_subject__normal(self):
    """Most intents just use the name of the intent."""
    self.assertEqual(
        'Intent to Prototype: feature one',
        notifier.generate_thread_subject(
            self.fe_1, approval_defs.PrototypeApproval))
    self.assertEqual(
        'Intent to Experiment: feature one',
        notifier.generate_thread_subject(
            self.fe_1, approval_defs.ExperimentApproval))
    self.assertEqual(
        'Intent to Extend Experiment: feature one',
        notifier.generate_thread_subject(
            self.fe_1, approval_defs.ExtendExperimentApproval))
    self.assertEqual(
        'Intent to Ship: feature one',
        notifier.generate_thread_subject(
            self.fe_1, approval_defs.ShipApproval))

  def test_generate_thread_subject__deprecation(self):
    """Deprecation intents use different subjects for most intents."""
    self.fe_1.feature_type = core_enums.FEATURE_TYPE_DEPRECATION_ID
    self.assertEqual(
        'Intent to Deprecate and Remove: feature one',
        notifier.generate_thread_subject(
            self.fe_1, approval_defs.PrototypeApproval))
    self.assertEqual(
        'Request for Deprecation Trial: feature one',
        notifier.generate_thread_subject(
            self.fe_1, approval_defs.ExperimentApproval))
    self.assertEqual(
        'Intent to Extend Deprecation Trial: feature one',
        notifier.generate_thread_subject(
            self.fe_1, approval_defs.ExtendExperimentApproval))
    self.assertEqual(
        'Intent to Ship: feature one',
        notifier.generate_thread_subject(
            self.fe_1, approval_defs.ShipApproval))


  def test_get_thread_id__trailing_junk(self):
    """We can select the correct approval thread field of a feature."""
    self.proto_stage.intent_thread_url += '?param=val#anchor'
    self.assertEqual(
        '123xxx=yyy@mail.gmail.com',
        notifier.get_thread_id(self.proto_stage))
