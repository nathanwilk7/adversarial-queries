SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((((complete_cast CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN movie_info) CROSS JOIN movie_keyword) CROSS JOIN kind_type) CROSS JOIN person_info) CROSS JOIN keyword) CROSS JOIN aka_name) CROSS JOIN name) CROSS JOIN info_type
WHERE info_type.info = 'LD production country'
  AND kind_type.kind = 'movie'
  AND aka_name.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
