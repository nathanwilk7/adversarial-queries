SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((cast_info CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN aka_name) CROSS JOIN movie_keyword) CROSS JOIN kind_type) CROSS JOIN keyword) CROSS JOIN name) CROSS JOIN person_info
WHERE cast_info.nr_order > 7
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
