"""Periodic exact anchors, timing-drift quarantine and explicit independent recovery."""
from copy import deepcopy
import math
from time import perf_counter
from .adaptive import AdaptiveController, LEVELS, TIERS
from .benchmark import relative_error
from .split_policy import CostAwareSession, execute_pair


def validate_profile(profile):
    AdaptiveController(profile)  # Identity correction at exact level, finite gains/bounds.
    for predicate in profile['countries']:
        for kind in ('node', 'edge'):
            for fidelity in LEVELS:
                value = profile['component_timing'][predicate][kind][str(fidelity)]
                if not math.isfinite(value) or value <= 0:
                    raise ValueError('Positive finite component timing required')


class AuditedSession:
    def __init__(self, backend, profile, build_ms, reuse_requests, sample_seed=25000,
                 mode='amortized', audit_every=10, timing_factor=3., timing_patience=3):
        if type(audit_every) is not int or audit_every < 1 or type(timing_patience) is not int or timing_patience < 1:
            raise ValueError('Positive integer audit interval and timing patience required')
        if not math.isfinite(timing_factor) or timing_factor <= 1:
            raise ValueError('Timing factor must exceed one')
        validate_profile(profile)
        self.backend, self.audit_every = backend, audit_every
        self.timing_factor, self.timing_patience = timing_factor, timing_patience
        self.session = CostAwareSession(backend, deepcopy(profile), build_ms, reuse_requests, sample_seed, mode)
        self.state, self.reason = 'active', None
        self.approximate_requests, self.timing_streak = 0, 0
        self.first_audit, self.profile_epoch = True, 0
        self.seen_sample_seeds, self.events = set(), []
        self.checked_predicates = set()

    def request(self, predicate, tier='balanced'):
        if tier not in TIERS:
            raise ValueError('Unknown tier')
        start = perf_counter()
        profile = self.session.profile
        if self.state == 'quarantined':
            result = execute_pair(self.session.cache, profile, predicate, (1., 1.))
            result.update(candidate=None, audited=False, audit_errors=None, audit_ms=0.,
                timing_ratio=None, build_ms=0., quarantined=True, reason=self.reason,
                state=self.state,
                profile_epoch=self.profile_epoch, online_ms=1000*(perf_counter()-start))
            return result
        try:
            candidate = self.session.request(predicate, tier)
        except RuntimeError as exc:
            if str(exc) != 'Sample was invalidated or refreshed':
                raise
            self.state, self.reason = 'quarantined', 'sample_invalidated'
            self.events.append(dict(event='quarantined', reason=self.reason, profile_epoch=self.profile_epoch))
            result = execute_pair(self.session.cache, profile, predicate, (1., 1.))
            result.update(candidate=None, audited=False, audit_errors=None, audit_ms=0.,
                timing_ratio=None, build_ms=0., quarantined=True, reason=self.reason,
                state=self.state,
                failed_attempt=True, query_count_complete=False,
                profile_epoch=self.profile_epoch, online_ms=1000*(perf_counter()-start))
            return result
        approximate = candidate['node_fidelity'] < 1 or candidate['edge_fidelity'] < 1
        if any(step['fidelity'] < 1 for step in candidate['steps']):
            self.seen_sample_seeds.add(self.session.sample_seed)
        if approximate:
            self.approximate_requests += 1
        timing_ratio, anchor, audit_errors = None, None, None
        audit_ms, detection = 0., None
        if approximate:
            forecast = sum(profile['component_timing'][predicate][s['kind']][str(s['fidelity'])]
                           for s in candidate['steps'])
            timing_ratio = candidate['request_ms']/forecast
            drift = timing_ratio > self.timing_factor or timing_ratio < 1/self.timing_factor
            self.timing_streak = self.timing_streak+1 if drift else 0
            if self.timing_streak >= self.timing_patience:
                detection = 'timing_drift'
            if self.first_audit or predicate not in self.checked_predicates or self.approximate_requests % self.audit_every == 0:
                anchor = execute_pair(self.session.cache, profile, predicate, (1., 1.))
                audit_ms = anchor['request_ms']
                audit_errors = [relative_error(candidate[k+'_estimate'], anchor[k+'_estimate'])
                                for k in ('node', 'edge')]
                self.first_audit = False
                self.checked_predicates.add(predicate)
                if any(e > b for e, b in zip(audit_errors, TIERS[tier])):
                    detection = 'error_budget'
                elif self.state == 'probing' and detection is None:
                    self.state = 'active'
                    self.events.append(dict(event='recovered', profile_epoch=self.profile_epoch))
        else:
            self.timing_streak = 0
        result = dict(candidate)
        if detection:
            self.state, self.reason = 'quarantined', detection
            self.events.append(dict(event='quarantined', reason=detection,
                                    approximate_request=self.approximate_requests, profile_epoch=self.profile_epoch))
            if anchor is None:
                anchor = execute_pair(self.session.cache, profile, predicate, (1., 1.))
                audit_ms = anchor['request_ms']
            for field in ('node_estimate', 'edge_estimate', 'node_fidelity', 'edge_fidelity'):
                result[field] = anchor[field]
        result['steps'] = candidate['steps'] + (anchor['steps'] if anchor is not None else [])
        result.update(candidate=candidate, audited=audit_errors is not None, audit_errors=audit_errors,
            audit_ms=audit_ms, timing_ratio=timing_ratio, quarantined=self.state == 'quarantined',
            state=self.state, reason=self.reason, profile_epoch=self.profile_epoch, online_ms=1000*(perf_counter()-start))
        return result

    def refresh(self, profile, build_ms, sample_seed):
        """Prepare externally on independent seeds; first approximate result must pass an anchor."""
        validate_profile(profile)
        if type(sample_seed) is not int or sample_seed < 0:
            raise ValueError('Nonnegative integer recovery sample seed required')
        if profile['graph_sha256'] != self.session.cache.fingerprint:
            raise ValueError('Recovery requires a matching static graph snapshot')
        fitting, calibration = set(profile['fitting_seeds']), set(profile['calibration_seeds'])
        if (len(fitting) < 2 or len(calibration) < 20 or fitting & calibration
                or (fitting | calibration) & (self.seen_sample_seeds | {sample_seed})
                or sample_seed in self.seen_sample_seeds):
            raise ValueError('Recovery training/calibration/evaluation seeds must be independent')
        new_session = CostAwareSession(self.backend, deepcopy(profile), build_ms,
            self.session.reuse_requests, sample_seed, self.session.mode)
        self.session = new_session
        self.profile_epoch += 1
        self.state, self.reason = 'probing', None
        self.first_audit, self.timing_streak, self.approximate_requests = True, 0, 0
        self.checked_predicates = set()
        self.events.append(dict(event='profile_refreshed', profile_epoch=self.profile_epoch))
