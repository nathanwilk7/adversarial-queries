SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((person_info CROSS JOIN (title CROSS JOIN cast_info)) CROSS JOIN aka_name) CROSS JOIN movie_keyword) CROSS JOIN kind_type) CROSS JOIN name
WHERE cast_info.nr_order = 17
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_keyword.movie_id = title.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
