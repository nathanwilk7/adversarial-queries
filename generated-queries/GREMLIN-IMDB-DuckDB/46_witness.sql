SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((((cast_info CROSS JOIN movie_link) CROSS JOIN title) CROSS JOIN name) CROSS JOIN movie_keyword) CROSS JOIN aka_name) CROSS JOIN char_name) CROSS JOIN keyword) CROSS JOIN person_info) CROSS JOIN link_type
WHERE char_name.name_pcode_nf = 'H5241'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
