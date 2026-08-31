SELECT count(*)
FROM aka_title, cast_info, company_type, movie_companies, movie_info, movie_info_idx, movie_link, name, person_info, role_type, title
WHERE aka_title.season_nr = 2
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
