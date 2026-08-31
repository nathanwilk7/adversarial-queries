SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((((((aka_title CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN info_type) CROSS JOIN movie_keyword) CROSS JOIN keyword) CROSS JOIN name) CROSS JOIN char_name) CROSS JOIN complete_cast) CROSS JOIN person_info) CROSS JOIN link_type) CROSS JOIN cast_info
WHERE info_type.info = 'LD production country'
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND complete_cast.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
