# Data interpretation and limitations

## Scope

The report studies associations between daily weather observations and sentiment
expressed in social media posts. The data do not establish that weather causes
changes in population mood. Platform audiences, posting behavior, topic trends
and uneven geographic coverage may affect the observations.

## Processing terminology

- A raw post is a record collected from one of the three social sources.
- An analytical post has been filtered, deduplicated, normalized and assigned a
  VADER sentiment score.
- A daily weather record represents city/date weather observations.
- The join matches many posts to the weather record for their city and date.

The 13 May 2026 counts are 1,386,354 raw posts, 1,218,705 analytical posts and
12,453 weather rows. The report provides the snapshot; the original live cluster
has not been accessed or independently audited for this portfolio copy.

## Limitations described by the report

- VADER can misread sarcasm, irony, domain-specific language and context.
- Social platform coverage and historical availability are uneven.
- Geographic assignment and timestamps require careful interpretation.
- University cloud resource constraints affected performance and operation.
- Manually integrating Kubernetes, Fission and Elasticsearch increased debugging
  and deployment complexity.

Raw posts and user identifiers are omitted. Future reproduction requires
authorized access to source APIs and data, appropriate treatment of platform
terms, and a review of the original project configuration.
