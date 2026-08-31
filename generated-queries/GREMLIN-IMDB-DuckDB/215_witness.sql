SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((((info_type CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN name) CROSS JOIN movie_keyword) CROSS JOIN complete_cast) CROSS JOIN keyword) CROSS JOIN movie_info) CROSS JOIN link_type) CROSS JOIN person_info
WHERE keyword.phonetic_code = 'R1652'
  AND name.imdb_index = 'XC'
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
