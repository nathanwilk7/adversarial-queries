SELECT count(*)
FROM aka_name, cast_info, char_name, company_name, info_type, keyword, kind_type, movie_companies, movie_info_idx, movie_keyword, movie_link, name, person_info, role_type, title
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
