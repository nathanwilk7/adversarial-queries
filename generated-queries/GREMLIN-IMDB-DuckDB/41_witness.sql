SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((cast_info CROSS JOIN aka_name) CROSS JOIN title) CROSS JOIN char_name) CROSS JOIN movie_keyword) CROSS JOIN name) CROSS JOIN keyword) CROSS JOIN info_type) CROSS JOIN person_info
WHERE char_name.name_pcode_nf = 'H5241'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
