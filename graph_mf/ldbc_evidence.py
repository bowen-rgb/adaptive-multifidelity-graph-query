"""Verify official-driver evidence without interpreting paced throughput as capacity."""
import math
import re


def schedule_audits(log, expected_phases=None):
    phases = re.findall(r'\b(PASSED|FAILED) SCHEDULE AUDIT\b', log)
    complete = expected_phases is None or len(phases) == expected_phases
    return dict(phases=phases, measurement_pass=complete and bool(phases) and phases[-1] == 'PASSED',
                all_phases_pass=bool(phases) and all(x == 'PASSED' for x in phases))


def service_metrics(result):
    if result.get('unit') != 'MILLISECONDS':
        raise ValueError('Official runtime units must be MILLISECONDS')
    operations = {}
    for metric in result['all_metrics']:
        name, count, runtime = metric['name'], metric['count'], metric['run_time']
        if name in operations or type(count) is not int or count <= 0:
            raise ValueError('Unique, positive operation counts required')
        if runtime['unit'] != 'MILLISECONDS' or runtime['count'] != count:
            raise ValueError('Inconsistent runtime count/units')
        average = runtime['mean']
        if not math.isfinite(average) or average < 0:
            raise ValueError('Finite nonnegative runtime required')
        operations[name] = dict(count=count, mean_ms=average, total_ms=count * average,
                                p95_ms=runtime['95th_percentile'])
    total = sum(x['count'] for x in operations.values())
    if total != result['total_count'] or total <= 0:
        raise ValueError('Metric counts disagree with official total_count')
    service = sum(x['total_ms'] for x in operations.values())
    return dict(actual_operations=total, executed_types=len(operations),
                cumulative_operation_ms=service, weighted_mean_ms=service / total,
                duration_ms=result['total_duration'], throughput_ops_s=result['throughput'],
                operations=operations,
                interpretation='sum of operation runtimes; not CPU time, wall time, or saturated capacity')
