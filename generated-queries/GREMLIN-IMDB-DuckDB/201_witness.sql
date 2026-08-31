SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((info_type CROSS JOIN movie_link) CROSS JOIN complete_cast) CROSS JOIN title) CROSS JOIN movie_keyword) CROSS JOIN person_info) CROSS JOIN movie_info) CROSS JOIN keyword) CROSS JOIN name
WHERE info_type.info = 'genres'
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
