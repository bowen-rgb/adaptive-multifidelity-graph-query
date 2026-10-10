"""Read-only IC3 message sampling pilot, separate from official exact validation.

The population lookup returns message IDs and country only, never answer counts.
All candidate people and KNOWS paths remain exact. Sampling scales messages by
1/f, and can lose people with messages in both countries or change their ranking.

CANDIDATES derives from LDBC SNB v1 IC3 at commit
11db98cc2ba14c33492f6c0c34e68c8be7e22e5f (Apache-2.0). Changes introduce
an ID-list message input and scaled aggregate counts. Original LICENSE/NOTICE
are retained in third_party/ldbc; Python sampling/quality functions are project code.
"""
import random

POPULATION = '''MATCH (m:Message)-[:IS_LOCATED_IN]->(c:Country)
WHERE c.name IN [$countryXName, $countryYName]
AND $endDate > m.creationDate >= $startDate
RETURN m.id AS id ORDER BY id'''

CANDIDATES = '''MATCH (countryX:Country {name:$countryXName}),
(countryY:Country {name:$countryYName}), (person:Person {id:$personId})
WITH person, countryX, countryY LIMIT 1
MATCH (city:City)-[:IS_PART_OF]->(country:Country)
WHERE country IN [countryX,countryY]
WITH person,countryX,countryY,collect(city) AS cities
MATCH (person)-[:KNOWS*1..2]-(friend)-[:IS_LOCATED_IN]->(city)
WHERE person <> friend AND NOT city IN cities
WITH DISTINCT friend,countryX,countryY
WITH collect(friend) AS friends,countryX,countryY
UNWIND $messageIds AS messageId
MATCH (message:Message {id:messageId})-[:HAS_CREATOR]->(friend)
WHERE friend IN friends
MATCH (message)-[:IS_LOCATED_IN]->(country)
WHERE $endDate > message.creationDate >= $startDate
AND country IN [countryX,countryY]
WITH friend, sum(CASE WHEN country=countryX THEN 1 ELSE 0 END)/$f AS xCount,
sum(CASE WHEN country=countryY THEN 1 ELSE 0 END)/$f AS yCount
WHERE xCount>0 AND yCount>0
RETURN friend.id AS friendId,friend.firstName AS friendFirstName,
friend.lastName AS friendLastName,xCount,yCount,xCount+yCount AS xyCount
ORDER BY xyCount DESC,friendId ASC LIMIT 20'''


def select_messages(ids, fidelity, seed):
    if not 0 < fidelity <= 1:
        raise ValueError('Fidelity must be in (0,1]')
    rng = random.Random(seed)
    return [identifier for identifier in ids if rng.random() < fidelity]


def quality(exact, approximate):
    """Top-20 quality; an absent exact person contributes 100% count error.

    Empty/empty recall is one; empty/nonempty is zero. Rank displacement is
    conditional on matched people; separately report missing and false people.
    """
    truth = {r['friendId']: (i, r) for i, r in enumerate(exact)}
    guessed = {r['friendId']: (i, r) for i, r in enumerate(approximate)}
    common = truth.keys() & guessed.keys()
    errors = []
    for person, (_, row) in truth.items():
        estimate = guessed.get(person, (None, {}))[1]
        errors.extend(abs(estimate.get(k, 0) - row[k]) / max(row[k], 1)
                      for k in ('xCount', 'yCount', 'xyCount'))
    return dict(recall=len(common)/len(truth) if truth else float(not guessed),
                missing=len(truth.keys()-guessed.keys()),
                false_people=len(guessed.keys()-truth.keys()),
                mean_count_error=sum(errors)/len(errors) if errors else 0.,
                max_count_error=max(errors, default=0.),
                mean_rank_displacement=sum(abs(truth[p][0]-guessed[p][0]) for p in common)/len(common) if common else 0.,
                exact_rows=len(exact), approximate_rows=len(approximate))
