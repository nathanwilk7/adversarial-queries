SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((((((((title CROSS JOIN movie_companies) CROSS JOIN movie_info_idx) CROSS JOIN movie_link) CROSS JOIN cast_info) CROSS JOIN kind_type) CROSS JOIN movie_keyword) CROSS JOIN info_type) CROSS JOIN company_name) CROSS JOIN name) CROSS JOIN role_type) CROSS JOIN char_name) CROSS JOIN aka_name) CROSS JOIN keyword) CROSS JOIN person_info
WHERE company_name.name_pcode_sf = ''
  AND movie_info_idx.info = '...02401..'
  AND movie_info_idx.note = ''
  AND title.season_nr > 2
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info_idx.info_type_id = info_type.id
  AND movie_info_idx.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
