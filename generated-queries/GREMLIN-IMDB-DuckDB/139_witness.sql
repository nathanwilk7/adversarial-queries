SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((((aka_title CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN movie_info) CROSS JOIN movie_keyword) CROSS JOIN name) CROSS JOIN complete_cast) CROSS JOIN link_type) CROSS JOIN keyword) CROSS JOIN person_info) CROSS JOIN info_type
WHERE info_type.info = 'LD production country'
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
