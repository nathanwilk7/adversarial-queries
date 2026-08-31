SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((((complete_cast CROSS JOIN info_type) CROSS JOIN movie_keyword) CROSS JOIN title) CROSS JOIN person_info) CROSS JOIN aka_name) CROSS JOIN keyword) CROSS JOIN name) CROSS JOIN link_type) CROSS JOIN movie_info) CROSS JOIN movie_link
WHERE aka_name.imdb_index = ''
  AND aka_name.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
