SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((movie_link CROSS JOIN (((aka_title CROSS JOIN (info_type CROSS JOIN title)) CROSS JOIN complete_cast) CROSS JOIN movie_info)) CROSS JOIN movie_keyword) CROSS JOIN name) CROSS JOIN person_info) CROSS JOIN kind_type
WHERE name.imdb_index = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
