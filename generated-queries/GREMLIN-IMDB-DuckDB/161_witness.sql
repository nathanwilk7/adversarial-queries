SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((comp_cast_type CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN cast_info) CROSS JOIN movie_keyword) CROSS JOIN name) CROSS JOIN keyword) CROSS JOIN complete_cast) CROSS JOIN person_info
WHERE name.gender = 'm'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND complete_cast.status_id = comp_cast_type.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
