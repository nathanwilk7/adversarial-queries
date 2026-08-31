SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((name CROSS JOIN (title CROSS JOIN cast_info)) CROSS JOIN movie_link) CROSS JOIN aka_title) CROSS JOIN kind_type) CROSS JOIN link_type
WHERE name.imdb_index = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
