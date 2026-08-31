SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((complete_cast CROSS JOIN title) CROSS JOIN aka_name) CROSS JOIN info_type) CROSS JOIN movie_keyword) CROSS JOIN movie_link) CROSS JOIN movie_info) CROSS JOIN person_info) CROSS JOIN name
WHERE info_type.info = 'LD production country'
  AND aka_name.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
